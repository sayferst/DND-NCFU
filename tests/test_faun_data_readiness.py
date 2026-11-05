"""A data-ready claim must survive corrupt reports, loss masks and leaked holdouts."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_training_pipeline import sample
from test_training_tokenization import CharacterTokenizer, corpus

from training.check_faun_data import check, check_loss_masks, corpus_summary
from training.tokenize_dataset import encode_dataset
from training.train_lora import preflight


def bound_config(tmp_path):
    config = corpus(tmp_path)
    root = Path(config["dataset"])
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    # These fixture inputs must describe different known scenes, not conflicting replies.
    for index, name in enumerate(("train", "val", "test")):
        path = root / (name + ".jsonl")
        row = json.loads(path.read_text(encoding="utf-8"))
        row["public_context"]["place"] += str(index)
        raw = (json.dumps(row, ensure_ascii=False) + "\n").encode()
        path.write_bytes(raw)
        manifest["file_sha256"][name] = hashlib.sha256(raw).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _, report = encode_dataset(config, CharacterTokenizer())
    path = tmp_path / "cpu-report.json"
    raw = json.dumps(report).encode()
    path.write_bytes(raw)
    config.update(
        cpu_tokenization_report=str(path),
        cpu_tokenization_report_sha256=hashlib.sha256(raw).hexdigest(),
    )
    return config


def test_integrity_only_never_claims_fresh_tokenizer_or_gpu_verification(tmp_path):
    config = bound_config(tmp_path)
    result = check(config)
    assert result["status"] == "INTEGRITY_PASS_TOKENIZATION_NOT_RERUN"
    assert result["corpus"]["samples"] == 3
    assert result["independent_auto_tokenizer_samples"] == 0
    assert not result["model_weights_loaded"] and not result["gpu_fit_verified"]
    assert result["corpus"]["human_reviewed_samples"] == 0
    assert result["training_steps"] == 0
    assert preflight(config).startswith("BLOCKED_MODEL")


@pytest.mark.parametrize(
    "failure", ["missing", "bytes", "schema", "corpus", "length", "drop", "count"]
)
def test_dry_run_rejects_changed_cpu_report_before_missing_model(tmp_path, failure):
    config = bound_config(tmp_path)
    path = Path(config["cpu_tokenization_report"])
    report = json.loads(path.read_text(encoding="utf-8"))
    if failure == "missing":
        path.unlink()
    elif failure == "bytes":
        path.write_text("{}", encoding="utf-8")
    else:
        if failure == "schema":
            report["schema"] = "unverified"
        elif failure == "corpus":
            report["dataset_sha256"] = "other-corpus"
        elif failure == "length":
            report["max_length"] = 4096
        elif failure == "drop":
            report["dropped_samples"] = 1
        elif failure == "count":
            report["splits"]["test"]["samples"] = 0
        raw = json.dumps(report).encode()
        path.write_bytes(raw)
        config["cpu_tokenization_report_sha256"] = hashlib.sha256(raw).hexdigest()
    assert preflight(config).startswith("BLOCKED_DATA")
    with pytest.raises((ValueError, OSError)):
        check(config)


def test_no_report_cannot_be_presented_as_final_ready(tmp_path):
    config = bound_config(tmp_path)
    del config["cpu_tokenization_report"]
    with pytest.raises(ValueError, match="bind a CPU"):
        check(config)
    with pytest.raises(ValueError, match="local tokenizer"):
        check(config, independent=True)


@pytest.mark.parametrize("failure", ["prompt_loss", "target_loss", "end", "attention", "truncate"])
def test_loss_mask_checker_finds_errors_even_when_token_count_is_right(failure):
    row = {
        "input_ids": [9, 10, 5, 6, 7],
        "labels": [-100, -100, 5, 6, 7],
        "attention_mask": [1] * 5,
    }
    report = {"splits": {"train": {"lengths": [{"prompt": 2, "answer": 3}]}}}
    assert check_loss_masks({"train": [row]}, report, [6, 7]) == 1
    changed = deepcopy(row)
    if failure == "prompt_loss":
        changed["labels"][0] = 9
    elif failure == "target_loss":
        changed["labels"][2] = -100
    elif failure == "end":
        changed["labels"][-1] = changed["input_ids"][-1] = 8
    elif failure == "attention":
        changed["attention_mask"][2] = 0
    elif failure == "truncate":
        changed["input_ids"].pop()
    with pytest.raises(ValueError, match="loss mask or ChatML"):
        check_loss_masks({"train": [changed]}, report, [6, 7])


def test_same_input_with_different_replies_cannot_be_independent_holdout():
    with pytest.raises(ValueError, match="duplicate full narrator input"):
        corpus_summary({"train": [sample(0, "a")], "test": [sample(1, "b")]})
    b = sample(1, "a")
    b["player_message"] = "Иду дальше"
    with pytest.raises(ValueError, match="group crosses splits"):
        corpus_summary({"train": [sample(0, "a")], "test": [b]})
