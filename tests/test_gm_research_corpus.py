"""Research-native outputs remain separate from approved QLoRA data."""

import gzip
import json

import pytest

from training.gm_candidate_audit import file_digest
from training.gm_research_corpus import POLICY, STATUS, export, verify
from training.train_lora import preflight


def prepared(tmp_path):
    cases, ledger = [], []
    for split in ("train", "val", "test"):
        case = {
            "id": split,
            "source": "FIREBALL",
            "split": split,
            "group_id": split,
            "source_unit": split + ":10",
            "context": {
                "task": "continue_dm_scene",
                "history": [{"text": "I ask about " + split + "."}],
            },
            "target": "The keeper considers your question about " + split + " carefully.",
            "provenance": {"source_language": "en"},
            "mechanics_evidence": {},
        }
        cases.append(case)
        ledger.append(
            {"id": split, "review_reasons": [], "total_tokens": 50, "assistant_tokens": 12}
        )
    # Same reply in train and test must stay outside the primary curriculum.
    for split in ("train", "test"):
        case = dict(cases[0]) | {
            "id": "duplicate-" + split,
            "split": split,
            "group_id": "duplicate-" + split,
            "target": "The keeper closes the heavy door with a loud thud.",
            "context": {"task": "continue_dm_scene", "history": [{"text": "Different " + split}]},
        }
        cases.append(case)
        ledger.append(
            {"id": case["id"], "review_reasons": [], "total_tokens": 50, "assistant_tokens": 12}
        )
    path, audit = tmp_path / "cases.gz", tmp_path / "audit"
    audit.mkdir()
    for p, values in ((path, cases), (audit / "audit-ledger.jsonl.gz", ledger)):
        with gzip.open(p, "wt", encoding="utf-8") as f:
            for row in values:
                f.write(json.dumps(row) + "\n")
    (audit / "report.json").write_text(
        json.dumps(
            {
                "source_cases_sha256": file_digest(path),
                "rows": len(cases),
                "independent_auto_tokenizer_samples": len(cases),
            }
        ),
        encoding="utf-8",
    )
    return path, audit


def test_cross_fold_source_replies_are_accounted_and_quarantined(tmp_path):
    path, audit = prepared(tmp_path)
    output = tmp_path / "native"
    result = export(path, audit, output)
    assert result["samples"] == 3
    assert result["review_reasons"]["IDENTICAL_SOURCE_REPLY_CROSSES_FOLDS"] == 2
    assert result["status"] == STATUS and result["train_admitted"] == 0
    _, splits = verify(output)
    assert all(row["train_admitted"] is False for values in splits.values() for row in values)


def test_research_data_is_blocked_before_model_loading_or_hardware(tmp_path):
    path, audit = prepared(tmp_path)
    output = tmp_path / "native"
    manifest = export(path, audit, output)
    result = preflight(
        {
            "dataset": str(output),
            "dataset_sha256": manifest["sha256"],
            "dataset_policy": POLICY,
            "model_path": str(tmp_path / "absent"),
        }
    )
    assert result.startswith("BLOCKED_DATA: source research corpus")


def test_changed_gzip_split_cannot_pass_research_integrity(tmp_path):
    path, audit = prepared(tmp_path)
    output = tmp_path / "native"
    export(path, audit, output)
    with (output / "train.jsonl.gz").open("ab") as f:
        f.write(b"tampered")
    with pytest.raises(ValueError, match="split bytes changed"):
        verify(output)


def test_incomplete_independent_token_audit_cannot_be_exported(tmp_path):
    path, audit = prepared(tmp_path)
    p = audit / "report.json"
    report = json.loads(p.read_text(encoding="utf-8"))
    report["independent_auto_tokenizer_samples"] = 0
    p.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="Complete independent"):
        export(path, audit, tmp_path / "native")
