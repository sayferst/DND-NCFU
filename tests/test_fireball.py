"""Authored fixtures exercise FIREBALL filters, provenance, grouping and training admission."""

import hashlib
import json

import pytest

from training.fireball import extract, hp
from training.tokenize_dataset import messages_for


def fixture_source(tmp_path, *, shared=False):
    manifest = {"revision": "test-only", "files": []}
    for i in range(3):
        actor = {
            "name": f"PrivateName{i}",
            "controller_id": "shared" if shared else str(i),
            "hp": f"<{10 + i}/20 HP; Injured>",
            "description": "secret plot ignored",
        }
        row = {
            "combat_state_before": [actor],
            "combat_state_after": [actor | {"hp": "<0/20 HP; Critical>"}],
            "before_utterances": ["untrusted dialogue ignored"],
        }
        raw = json.dumps(row).encode()
        name = str(i) + ".jsonl"
        (tmp_path / name).write_bytes(raw)
        manifest["files"].append({"path": name, "sha256": hashlib.sha256(raw).hexdigest()})
    (tmp_path / "source-manifest.json").write_text(json.dumps(manifest))
    return tmp_path


def test_grouped_source_states_have_correct_russian_numbers_and_no_death_inference(tmp_path):
    parts, report = extract(fixture_source(tmp_path))
    assert report["accepted"] == 3 and report["external_holdout_available"]
    assert all(len(rows) == 1 for rows in parts.values())
    for rows in parts.values():
        row = rows[0]
        assert "Смерть при 0 HP этим снимком не подтверждена" in row["assistant_reply"]
        text = json.dumps(messages_for(row), ensure_ascii=False)
        assert "PrivateName" not in text and "controller" not in text and "secret" not in text
        assert row["assistant_reply"] not in text
        assert row["source"]["line_sha256"] and row["human_reviewed"] is False


def test_shared_participants_never_cross_splits_and_insufficient_groups_reported(tmp_path):
    parts, report = extract(fixture_source(tmp_path, shared=True))
    assert report["independent_groups"] == 1 and not report["external_holdout_available"]
    assert len(parts["train"]) == 3 and not parts["val"] and not parts["test"]


@pytest.mark.parametrize("value", ["<32/20 HP; Healthy>", "<Bloodied>", "<4/10 HP (+3 temp)>", ""])
def test_unknown_temporary_and_overcap_hp_not_guessed(value):
    with pytest.raises(ValueError):
        hp(value)


def test_source_changes_are_rejected_before_import(tmp_path):
    root = fixture_source(tmp_path)
    (root / "0.jsonl").write_text("{}")
    with pytest.raises(ValueError, match="source changed"):
        extract(root)
