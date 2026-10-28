import json

from training.schema import validate
from training.synthetic_audit import PROVENANCE, audit, issues


def sample(id="one", family="family"):
    return {
        "schema_version": "gm-sft-v1",
        "sample_id": id,
        "campaign_id": family,
        "scene_mode": "inspect_area",
        "public_context": {},
        "player_message": "Осматриваюсь",
        "engine_receipt": {"provenance": PROVENANCE, "changes": [], "rolls": []},
        "assistant_reply": "Над дорогой поднимается туман.",
        "synthetic": True,
        "review_status": "pending",
        "rights_status": "synthetic_original_unreviewed",
    }


def test_provenance_cannot_be_laundered_by_relabeling():
    row = sample()
    row.update(synthetic=False, review_status="approved", rights_status="permitted")
    assert validate(row) == (False, "fixture_not_training_data")


def test_audit_detects_arithmetic_and_rejected_mutations():
    row = sample()
    row["scene_mode"] = "spell_no_mana"
    row["engine_receipt"]["rolls"] = [{"die": "d20", "face": 21, "total": 21}]
    row["engine_receipt"]["changes"] = [{"field": "hero.mp", "before": 1, "after": -1}]
    assert {"die_range", "negative_balance", "rejected_action_changed_state"} <= set(issues(row))


def test_group_disjoint_is_not_claimed_as_template_disjoint(tmp_path):
    path = tmp_path / "synthetic.jsonl"
    rows = [sample(str(i), str(i)) for i in range(100)]
    original = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    path.write_text(original, encoding="utf-8")
    report = audit(path)
    assert report["proposed_split_counts"] == {"train": 80, "val": 10, "test": 10}
    assert report["templates_shared_between_splits"] == 1
    assert not report["production_ready"] and not report["training_started"]
    assert report["issues"]["real_pipeline_rejected"] == 100
    assert path.read_text(encoding="utf-8") == original
