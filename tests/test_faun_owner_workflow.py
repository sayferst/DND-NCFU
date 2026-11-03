"""Owner tooling uses synthetic fixtures here, never actual model weights or private saves."""

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile

import pytest
from test_local_narrator import local_server
from test_training_pipeline import sample

from rpg_vkr.narrative.ollama import OllamaClient
from training import game_benchmark
from training.evaluate_faun import evaluate, holdout
from training.ollama_probe import FAUN_MODEL
from training.setup_faun_gpu import bundle
from training.suggest_annotations import suggest
from training.train_lora import run_signature, validate_resume


def test_all_authored_game_contracts_replay_without_model_or_network():
    def forbidden(*a, **k):
        raise AssertionError("No model call is authorized in contract-only mode")

    result = game_benchmark.run(limit=len(game_benchmark.CASES), narrator=forbidden)
    assert len(result["cases"]) == 11 and result["accepted_replies"] == 0
    assert result["status"] == "CONTRACTS_PASSED_MODEL_NOT_RUN"
    assert all(c["save_replay_equal"] for c in result["cases"])
    impossible = [c for c in result["cases"] if c["id"] in ("broom", "coins", "coins_no_magic")]
    assert all(
        c["receipt"]["free_attempt"]["mode"] == "ATTEMPT_WITHOUT_TARGET_SUCCESS"
        and not c["receipt"]["dice"]
        for c in impossible
    )


def test_game_benchmark_marks_model_failure_and_rejects_remote_ollama_model():
    def tags(path):
        return {"models": [{"name": FAUN_MODEL, "size": 123, "digest": "test"}]}

    result = game_benchmark.run(
        live=True,
        limit=1,
        requester=tags,
        narrator=lambda *a: {"status": "rejected_or_unavailable"},
    )
    assert result["status"] == "LIVE_DEGRADED_REQUIRES_REVIEW"
    assert result["accepted_replies"] == 0
    result = game_benchmark.run(
        live=True,
        requester=lambda path: {
            "models": [{"name": FAUN_MODEL, "size": 123, "remote_host": "https://invalid"}]
        },
    )
    assert result["status"] == "BLOCKED_MODEL" and not result["cases"]


def test_real_ollama_client_gets_engine_context_without_applying_action_twice(qt_app):
    session, text = game_benchmark.execute_case("bow_partial")
    before = deepcopy(session.to_dict())
    with local_server(mode="plain_ok") as (url, requests):
        result = game_benchmark.narrate(
            session,
            text,
            FAUN_MODEL,
            client_factory=lambda **kwargs: OllamaClient(base_url=url, **kwargs),
        )
    chats = [raw for path, raw in requests if path == "/api/chat"]
    assert chats and all(c["model"] == FAUN_MODEL for c in chats)
    assert all("think" not in c for c in chats)
    assert "удоч" in str(chats) and "КВИТАНЦИЯ" in str(chats).upper()
    assert result["status"] in ("accepted", "rejected_or_unavailable")
    assert session.to_dict() == before


def test_rejected_benchmark_responses_remain_available_for_review(qt_app):
    session, text = game_benchmark.execute_case("bow_damage")
    before = deepcopy(session.to_dict())
    with local_server(mode="plain_always_bad") as (url, requests):
        result = game_benchmark.narrate(
            session,
            text,
            FAUN_MODEL,
            client_factory=lambda **kwargs: OllamaClient(base_url=url, **kwargs),
        )
    assert result["status"] == "rejected_or_unavailable"
    assert 1 <= len(result["response_diagnostics"]) <= 2
    assert all(len(d) <= 16000 for d in result["response_diagnostics"])
    assert "走近" in result["response_diagnostics"][-1]
    assert "Ответ" in result["response_diagnostics"][-1]
    assert session.to_dict() == before


def test_rules_and_optional_ai_never_approve_training_labels():
    rules = suggest()
    assert len(rules) == 800
    assert all(not r["human_approved"] and not r["train_admitted"] for r in rules)

    def invalid_ai(path, body=None):
        if path == "/api/tags":
            return {"models": [{"name": FAUN_MODEL, "size": 1}]}
        return {"message": {"content": '{"human_approved":true}'}}

    values = suggest(model=FAUN_MODEL, limit=1, requester=invalid_ai)
    assert values[0]["ai_suggestion"]["status"] == "HUMAN_REVIEW_REQUIRED"
    assert all(not r["human_approved"] for r in values)


def test_portable_bundle_contains_only_hashed_tools_and_runs_without_game_dependencies(tmp_path):
    path = tmp_path / "tools.zip"
    manifest = bundle(path)
    assert manifest["training_steps"] == 0 and not manifest["weights_included"]
    with ZipFile(path) as z:
        for name, sha in manifest["files"].items():
            assert hashlib.sha256(z.read(name)).hexdigest() == sha
            assert not any(token in name for token in ("saves/", ".env", "api-key", "data/"))
        z.extractall(tmp_path / "portable")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "training.train_lora",
            "--config",
            "training/configs/faun_qlora_v1.json",
            "--dry-run",
        ],
        cwd=tmp_path / "portable",
        capture_output=True,
        text=True,
        check=True,
    )
    assert "BLOCKED_DATA" in result.stdout
    with pytest.raises(FileExistsError):
        bundle(path)


def test_resume_rejects_other_run_or_changed_configuration(tmp_path):
    config = {"output": str(tmp_path / "run"), "seed": 37}
    output = Path(config["output"])
    checkpoint = output / "checkpoint-100"
    checkpoint.mkdir(parents=True)
    (output / "run-provenance.json").write_text(
        json.dumps({"config_sha256": run_signature(config)}), encoding="utf-8"
    )
    (checkpoint / "trainer_state.json").write_text('{"global_step":100}', encoding="utf-8")
    assert validate_resume(config, checkpoint) == str(checkpoint)
    with pytest.raises(ValueError):
        validate_resume(config | {"seed": 38}, checkpoint)
    with pytest.raises(ValueError):
        validate_resume(config, tmp_path / "other/checkpoint-100")


def test_holdout_checks_hashes_and_never_invents_human_evaluation(tmp_path):
    directory = tmp_path / "prepared"
    directory.mkdir()
    hashes = {}
    for i, split in enumerate(("train", "val", "test")):
        raw = json.dumps(sample(i, str(i)), ensure_ascii=False).encode()
        (directory / (split + ".jsonl")).write_bytes(raw)
        hashes[split] = hashlib.sha256(raw).hexdigest()
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "status": "READY",
                "privacy_review_confirmed": True,
                "sha256": "fixture-dataset",
                "file_sha256": hashes,
            }
        ),
        encoding="utf-8",
    )
    _, rows = holdout(directory)
    assert rows

    def local(path, body=None):
        if path == "/api/tags":
            return {"models": [{"name": FAUN_MODEL, "size": 1, "digest": "fixture"}]}
        return {"message": {"content": "Стражник выслушивает ответ."}, "done": True}

    result = evaluate(directory, limit=1, requester=local)
    assert result["actual_inference"] and result["human_review"] is None
    assert result["samples"][0]["human_review_status"] == "PENDING"
    with (directory / "test.jsonl").open("a", encoding="utf-8") as stream:
        stream.write("\n{}")
    with pytest.raises(ValueError, match="split changed"):
        holdout(directory)
