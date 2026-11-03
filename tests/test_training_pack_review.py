"""Public authored fixtures only; no owner archive or fake human review in Git."""

import hashlib
import json
from copy import deepcopy
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from training.annotation_v2 import STATUS_RU, export, rows_v2
from training.jsonio import strict_json
from training.review_training_pack import audit, prepare_review, read_pack, repair_question_links
from training.schema import digest
from training.synthetic_corpus import CHECKS, prepare, validate, verify
from training.xlsx import NS


def write_pack(path, files):
    manifest = json.loads(files["manifest.json"])
    manifest["file_sha256"] = {
        n: hashlib.sha256(raw).hexdigest() for n, raw in files.items() if n != "manifest.json"
    }
    files = files | {"manifest.json": json.dumps(manifest).encode()}
    with ZipFile(path, "x") as z:
        for name, raw in files.items():
            z.writestr("pack/" + name, raw)


def jsonl(rows):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode()


@pytest.fixture(scope="module")
def proposal_pack(tmp_path_factory):
    folder = tmp_path_factory.mktemp("authored-pack")
    workbook = folder / "blank.xlsx"
    export(workbook)
    baseline = rows_v2()
    splits = {s: [] for s in ("train", "val", "test")}
    for b in baseline:
        index = int(b["id"].rsplit("_", 1)[1])
        split = "train" if index < 8 else "val" if index == 8 else "test"
        splits[split].append(
            {
                "scenario_id": b["id"],
                "family": b["family"],
                "condition_type": b["condition_type"],
                "review_track": b["review_track"],
                "context": b["context"],
                "items": b["items"],
                "skills": b["skills"],
                "player_message": b["action"],
                "split": split,
                "synthetic": True,
                "sft_admitted": False,
                "review_status": "AI_SUGGESTED",
                "attempt_possible": "Да",
                "goal_reachable": "Неясно",
                "d20_required": "Неясно",
                "outcomes": "Проверь факты.",
                "risks": "Неизвестны.",
                "consequences": "Нужна квитанция.",
                "blocking_questions": [],
            }
        )
    pair_rows = [r for r in baseline if r["id"].endswith("_0_0")]
    pairs = [
        {
            "scenario_id": b["id"],
            "synthetic": True,
            "sft_admitted": False,
            "source": "AI_AUTHORED_EXAMPLE",
            "review_status": "AI_SUGGESTED",
            "benchmark_only": True,
            "public_context": {"place": "Учебная сцена"},
            "player_message": b["action"],
            "mock_engine_receipt": {"provenance": "SYNTHETIC_EXAMPLE", "outcome": "no_change"},
            "preferred_reply": "Состояние осталось прежним.",
            "rejected_reply": "Все получили золото.",
            "rejection_reason": "Квитанция не создаёт золота.",
        }
        for b in pair_rows
    ]
    changes = {}
    for n, _b in enumerate(baseline, 2):
        changes.update(
            {
                f"{col}{n}": value
                for col, value in {
                    "G": "Да",
                    "H": "Неясно",
                    "I": "Неясно",
                    "J": "Проверь факты.",
                    "K": "Неизвестны.",
                    "L": "Нужна квитанция.",
                    "Q": STATUS_RU["AI_SUGGESTED"],
                }.items()
            }
        )
    reply_changes = {}
    for n, b in enumerate(baseline, 2):
        if b["id"] in {r["scenario_id"] for r in pairs}:
            reply_changes.update(
                {f"E{n}": "Состояние осталось прежним.", f"L{n}": STATUS_RU["AI_SUGGESTED"]}
            )
    output = BytesIO()
    with ZipFile(workbook) as src, ZipFile(output, "w") as dst:
        for name in src.namelist():
            raw = src.read(name)
            edits = (
                changes
                if name.endswith("sheet1.xml")
                else reply_changes
                if name.endswith("sheet2.xml")
                else {}
            )
            if edits:
                tree = ET.fromstring(raw)
                for cell in tree.iter("{" + NS + "}c"):
                    if cell.attrib["r"] in edits:
                        for child in list(cell):
                            cell.remove(child)
                        cell.set("t", "inlineStr")
                        ET.SubElement(
                            ET.SubElement(cell, "{" + NS + "}is"), "{" + NS + "}t"
                        ).text = edits[cell.attrib["r"]]
                raw = ET.tostring(tree)
            dst.writestr(name, raw)
    files = {f"synthetic_actions_{s}.jsonl": jsonl(rows) for s, rows in splits.items()}
    files.update(
        {
            "approved_rules_R01_R14.json": json.dumps(
                {"rules": {f"R{n:02}": "Authored test policy" for n in range(1, 15)}}
            ).encode(),
            "blocking_questions.jsonl": b"",
            "narrative_synthetic_pairs_40.jsonl": jsonl(pairs),
            "real_game_regression_observations_5.jsonl": b"",
            "scenarios-1000-v3-AI-proposed.xlsx": output.getvalue(),
            "manifest.json": json.dumps(
                {
                    "counts": {
                        "action_proposals": 1000,
                        "human_review_priority": 200,
                        "ai_later": 800,
                        "open_factual_questions": 0,
                        "synthetic_narrative_preference_pairs": 20,
                        "verified_engine_receipts": 0,
                        "approved_gm_sft_samples": 0,
                        "real_log_QA_observations": 0,
                    }
                }
            ).encode(),
        }
    )
    path = folder / "pack.zip"
    write_pack(path, files)
    return path


def decisions(tmp_path, files):
    p = tmp_path / "owner.json"
    p.write_text(
        json.dumps(
            {
                "schema": "dnd-owner-decisions-v1",
                "confirmation_source": "DIRECT_USER_REPLY",
                "approved_rules": [f"R{n:02}" for n in range(1, 15)],
                "synthetic_corpus_allowed": True,
                "human_reviewed_rows": 0,
                "budget_rub": 500,
                "rulebook_sha256": hashlib.sha256(files["approved_rules_R01_R14.json"]).hexdigest(),
            }
        )
    )
    return p


def editorial(tmp_path, files):
    rows = []
    for line in files["narrative_synthetic_pairs_40.jsonl"].splitlines():
        source = json.loads(line)
        answer = source["preferred_reply"]
        rows.append(
            {
                "scenario_id": source["scenario_id"],
                "assistant_reply": answer,
                "editorial_review": {
                    "kind": "ASSISTANT_EDITORIAL_REVIEWED",
                    "reviewer": "codex",
                    "human_reviewed": False,
                    "source_pair_sha256": digest(source),
                    "reply_sha256": digest(answer),
                    "checks": sorted(CHECKS),
                    "rationale": "Authored fixture review, no new fact.",
                },
            }
        )
    p = tmp_path / "editorial.jsonl"
    p.write_bytes(jsonl(rows))
    return p


def test_archive_claims_do_not_confirm_rules_or_human_approval(proposal_pack, tmp_path):
    report, _, files = audit(proposal_pack)
    assert report["status"] == "VALID_PROPOSALS_BLOCKED_DATA"
    assert report["counts"]["action_proposals"] == 1000 and report["sft_admitted"] == 0
    assert report["rulebook_status"] == "AWAITING_DIRECT_OWNER_CONFIRMATION"
    report, _, _ = audit(proposal_pack, owner_decisions=decisions(tmp_path, files))
    assert report["rulebook_status"] == "OWNER_CONFIRMED_RUNTIME_IMPLEMENTATION_NOT_VERIFIED"
    assert "RULEBOOK_CONFIRMATION_PENDING" not in report["blockers"]
    assert report["workbook_import"]["counts"]["action_labels"] == 1000


def test_repair_only_missing_generic_sidecar_link_preserves_original(proposal_pack, tmp_path):
    files = read_pack(proposal_pack)
    rows = [json.loads(line) for line in files["synthetic_actions_train.jsonl"].splitlines()]
    rows[0]["review_status"] = "HUMAN_REVIEW_REQUIRED"
    files["synthetic_actions_train.jsonl"] = jsonl(rows)
    files["blocking_questions.jsonl"] = jsonl(
        [
            {
                "id": rows[0]["scenario_id"],
                "questions": ["Не хватает параметров для окончательного решения исхода/проверки."],
            }
        ]
    )
    bad = tmp_path / "omitted.zip"
    write_pack(bad, files)
    before = bad.read_bytes()
    corrected = tmp_path / "repaired.zip"
    assert repair_question_links(bad, corrected) == [rows[0]["scenario_id"]]
    assert bad.read_bytes() == before
    actual = json.loads(read_pack(corrected)["synthetic_actions_train.jsonl"].splitlines()[0])
    assert actual["blocking_questions"] and actual["sft_admitted"] is False
    assert actual["review_status"] == "HUMAN_REVIEW_REQUIRED"
    with pytest.raises(FileExistsError):
        repair_question_links(bad, corrected)


def test_substantive_question_conflict_cannot_be_auto_repaired(proposal_pack, tmp_path):
    files = read_pack(proposal_pack)
    id = json.loads(files["synthetic_actions_train.jsonl"].splitlines()[0])["scenario_id"]
    files["blocking_questions.jsonl"] = jsonl([{"id": id, "questions": ["Какое HP?"]}])
    bad = tmp_path / "conflict.zip"
    write_pack(bad, files)
    with pytest.raises(ValueError, match="substantive"):
        repair_question_links(bad, tmp_path / "must-not-exist.zip")
    assert not (tmp_path / "must-not-exist.zip").exists()


def test_changed_archive_hash_never_stages_samples(proposal_pack, tmp_path):
    files = read_pack(proposal_pack)
    files["blocking_questions.jsonl"] = b"{}\n"
    bad = tmp_path / "tampered.zip"
    with ZipFile(bad, "x") as z:
        for name, raw in files.items():
            z.writestr(name, raw)
    result = prepare_review(bad, tmp_path / "out")
    assert result["status"] == "INVALID_PACK"
    assert not (tmp_path / "out/actions-review.jsonl").exists()


@pytest.mark.parametrize(
    "problem",
    ["source_fact", "fake_approval", "split_leak", "missing_workbook_labels", "workbook_reply"],
)
def test_semantic_archive_corruption_rejected_after_rehash(proposal_pack, tmp_path, problem):
    files = read_pack(proposal_pack)
    rows = [json.loads(line) for line in files["synthetic_actions_train.jsonl"].splitlines()]
    if problem == "source_fact":
        rows[0]["items"] = "Несуществующий предмет"
    elif problem == "fake_approval":
        rows[0]["review_status"] = "HUMAN_APPROVED"
    elif problem == "split_leak":
        test = [json.loads(line) for line in files["synthetic_actions_test.jsonl"].splitlines()]
        moved = rows.pop(0)
        moved["split"] = "test"
        test.append(moved)
        files["synthetic_actions_test.jsonl"] = jsonl(test)
    elif problem == "missing_workbook_labels":
        p = tmp_path / "blank.xlsx"
        export(p)
        files["scenarios-1000-v3-AI-proposed.xlsx"] = p.read_bytes()
    else:
        pairs = [
            json.loads(line) for line in files["narrative_synthetic_pairs_40.jsonl"].splitlines()
        ]
        pairs[0]["preferred_reply"] = "Иная строка без квитанции."
        files["narrative_synthetic_pairs_40.jsonl"] = jsonl(pairs)
    files["synthetic_actions_train.jsonl"] = jsonl(rows)
    path = tmp_path / "bad.zip"
    write_pack(path, files)
    assert audit(path)[0]["status"] == "INVALID_PACK"


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_ambiguous_json_rejected(raw):
    with pytest.raises(ValueError):
        strict_json(raw)


def test_synthetic_pilot_is_separate_bound_and_family_disjoint(proposal_pack, tmp_path):
    files = read_pack(proposal_pack)
    out = tmp_path / "pilot"
    result = prepare(proposal_pack, editorial(tmp_path, files), decisions(tmp_path, files), out)
    manifest, splits = verify(out)
    assert result["status"] == "PILOT_READY" and result["human_reviewed_samples"] == 0
    assert manifest["real_engine_receipts"] == 0 and manifest["synthetic_samples"] == 20
    families = [{r["family"] for r in v} for v in splits.values()]
    assert not any(a & b for i, a in enumerate(families) for b in families[i + 1 :])
    from training.schema import validate as validate_real

    row = splits["train"][0]
    assert validate(row)[0] and not validate_real(row)[0]
    for field, value in [
        ("assistant_reply", "Новые деньги."),
        ("human_reviewed", True),
        ("engine_receipt", {}),
    ]:
        bad = deepcopy(row)
        bad[field] = value
        assert not validate(bad)[0]
    (out / "val.jsonl").write_bytes((out / "train.jsonl").read_bytes())
    with pytest.raises(ValueError, match="split changed"):
        verify(out)
    with pytest.raises(FileExistsError):
        prepare(proposal_pack, editorial(tmp_path, files), tmp_path / "owner.json", out)


def test_owner_decisions_must_bind_exact_rulebook(proposal_pack, tmp_path):
    files = read_pack(proposal_pack)
    p = decisions(tmp_path, files)
    value = json.loads(p.read_text())
    value["rulebook_sha256"] = "0" * 64
    p.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="rulebook hash"):
        audit(proposal_pack, owner_decisions=p)


def test_pilot_transfer_requires_explicit_policy_and_cpu_report(proposal_pack, tmp_path):
    from training.prepare_faun_transfer import prepare as transfer
    from training.train_lora import preflight

    files = read_pack(proposal_pack)
    dataset = tmp_path / "pilot"
    manifest = prepare(
        proposal_pack, editorial(tmp_path, files), decisions(tmp_path, files), dataset
    )
    path = tmp_path / "transfer.zip"
    with pytest.raises(ValueError, match="BLOCKED_DATA"):
        transfer(path, dataset=dataset)
    with pytest.raises(ValueError, match="CPU first"):
        transfer(path, dataset=dataset, synthetic_pilot=True)
    assert not path.exists()
    cpu = tmp_path / "cpu.json"
    cpu.write_text(
        json.dumps(
            {
                "schema": "faun-cpu-tokenization-v1",
                "dataset_sha256": manifest["sha256"],
                "max_length": 2048,
                "dropped_samples": 0,
            }
        )
    )
    result = transfer(path, dataset=dataset, synthetic_pilot=True, cpu_report=cpu)
    assert result["synthetic_pilot"] is True and not result["dataset_included"]
    assert not result["cpu_report_included"]
    with ZipFile(path) as archive:
        assert (
            "faun-pilot.json" in archive.namelist() and "faun-full.json" not in archive.namelist()
        )
        config = json.loads(archive.read("faun-pilot.json"))
        assert config["dataset_policy"] == "synthetic-pilot-v1"
        assert config["dataset_sha256"] == manifest["sha256"]
        assert not any(n.endswith(".jsonl") for n in archive.namelist())
        for name in (
            "training/tokenize_dataset.py",
            "training/synthetic_corpus.py",
            "training/jsonio.py",
        ):
            assert name in archive.namelist()
    local_config = config | {"dataset": str(dataset)}
    assert preflight(local_config).startswith("BLOCKED_MODEL")
    local_config.pop("dataset_policy")
    assert preflight(local_config).startswith("BLOCKED_DATA")


def test_synthetic_forged_answer_review_and_private_context_rejected(proposal_pack, tmp_path):
    files = read_pack(proposal_pack)
    edit = editorial(tmp_path, files)
    reviews = [json.loads(line) for line in edit.read_text().splitlines()]
    reviews[0]["assistant_reply"] = "Отредактировано после проверки."
    edit.write_bytes(jsonl(reviews))
    output = tmp_path / "not-written"
    with pytest.raises(ValueError, match="unbound_editorial_review"):
        prepare(proposal_pack, edit, decisions(tmp_path, files), output)
    assert not output.exists()


def test_synthetic_evaluation_is_opt_in_and_never_claims_real_receipts(proposal_pack, tmp_path):
    from training.evaluate_faun import evaluate, holdout
    from training.ollama_probe import FAUN_MODEL

    files = read_pack(proposal_pack)
    folder = tmp_path / "pilot"
    prepare(proposal_pack, editorial(tmp_path, files), decisions(tmp_path, files), folder)
    with pytest.raises(ValueError, match="BLOCKED_DATA"):
        holdout(folder)
    _, test_rows = holdout(folder, synthetic_pilot=True)
    calls = []

    def requester(path, body=None):
        calls.append((path, body))
        if path == "/api/tags":
            return {
                "models": [
                    {"name": FAUN_MODEL, "digest": "authored-fake-installed-model", "size": 1}
                ]
            }
        return {"done": True, "message": {"content": "Состояние осталось прежним."}}

    report = evaluate(folder, limit=1, requester=requester, synthetic_pilot=True)
    assert report["synthetic_pilot"] is True and report["prompt_mode"] == "synthetic_mock_receipt"
    assert report["human_review"] is None and report["training_steps_by_this_command"] == 0
    assert report["samples"][0]["id"] == test_rows[0]["sample_id"]
    assert len(calls) == 2
