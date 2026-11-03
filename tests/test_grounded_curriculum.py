"""Synthetic admission and unseen compositions, using authored fixtures only."""

import json
from copy import deepcopy
from random import Random

import pytest

from training.annotation_v2 import rows_v2
from training.grounded_curriculum import build, compile_row, initial, resolve, specs
from training.grounded_validation import admit, audit, invariant_errors, verify
from training.schema import validate as validate_real


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    folder = tmp_path_factory.mktemp("grounded-reference") / "candidate"
    manifest = build(folder)
    return folder, manifest


def authorization(path):
    path.write_text(
        json.dumps(
            {
                "confirmation_source": "DIRECT_USER_REPLY",
                "synthetic_corpus_allowed": True,
                "synthetic_state_authoring_allowed": True,
                "knockout_zero_stable": True,
                "overcast_requires_full_hp": True,
                "approved_rules": [f"R{n:02}" for n in range(1, 15)],
            }
        )
    )
    return path


def test_full_source_and_rule_boundary_coverage_replays_without_human_claim(corpus):
    folder, manifest = corpus
    report, parts = audit(folder)
    assert report["status"] == "REFERENCE_AUDIT_PASS" and report["errors"] == []
    assert report["samples"] == 1100 and report["intent_groups"] == 220
    assert manifest["splits"] == {"train": 880, "val": 110, "test": 110}
    assert report["human_reviewed_samples"] == 0
    ids = {r["sample_id"] for rows in parts.values() for r in rows}
    assert {r["id"] for r in rows_v2()} <= ids
    assert len({row["player_message"] for rows in parts.values() for row in rows}) >= 200
    seen = {}
    for split, rows in parts.items():
        for row in rows:
            assert seen.setdefault(row["campaign_id"], split) == split
            assert not validate_real(row)[0]


def test_candidate_cannot_train_until_explicit_synthetic_admission(corpus, tmp_path):
    folder, _ = corpus
    with pytest.raises(ValueError, match="admitted"):
        verify(folder)
    output = tmp_path / "processed"
    policy = authorization(tmp_path / "owner.json")
    result = admit(folder, policy, output)
    manifest, splits = verify(output)
    assert result["status"] == manifest["status"] == "READY_SYNTHETIC"
    assert result["annotation_missing_fields"] == 0 and result["real_game_episodes"] == 0
    assert all(
        row["owner_authorization_sha256"] == manifest["owner_authorization_sha256"]
        for rows in splits.values()
        for row in rows
    )
    with pytest.raises(FileExistsError):
        admit(folder, policy, output)
    (output / "owner-authorization.json").write_text("{}")
    with pytest.raises(ValueError, match="authorization changed"):
        verify(output)


def test_archive_self_approval_does_not_replace_missing_owner_decisions(corpus, tmp_path):
    folder, _ = corpus
    policy = tmp_path / "self-approval.json"
    policy.write_text('{"status":"OWNER_APPROVED"}')
    with pytest.raises(ValueError, match="Explicit owner"):
        admit(folder, policy, tmp_path / "not-created")
    assert not (tmp_path / "not-created").exists()


def fresh_spec():
    return {
        "operation": "craft",
        "subject": "вторая походная трость",
        "goal": "опора для тента",
        "task": "repair",
        "success": "Опора подготовлена.",
        "partial": "Опора требует доработки.",
        "failure": "Опора не готова.",
        "parameters": {
            "input_traits": ["rigid"],
            "required_traits": ["rigid"],
            "result_capabilities": ["support"],
        },
    }


def high_seed():
    return next(seed for seed in range(1000) if Random(seed).randint(1, 20) == 20)


def test_new_item_combination_uses_same_executor_and_preserves_identity():
    source = rows_v2()[0]
    spec = fresh_spec()
    before = initial(source, spec)
    after, result, key = resolve(before, spec, high_seed())
    assert result["roll"]["natural"] == 20 and key == "success"
    assert after["objects"]["subject"]["properties"]["capabilities"] == ["support"]
    assert set(after["objects"]) == set(before["objects"])
    assert after["hero"]["gold"] == before["hero"]["gold"]
    assert after["objects"]["material"]["quantity"] == before["objects"]["material"]["quantity"] - 1


@pytest.mark.parametrize("capability", ["currency", "flight", "resurrection"])
def test_high_roll_cannot_add_unfunded_resources_or_impossible_effects(capability):
    source = rows_v2()[0]
    spec = fresh_spec()
    spec["parameters"]["result_capabilities"] = [capability]
    before = initial(source, spec)
    after, result, _ = resolve(before, spec, high_seed())
    assert result["outcome"] == "goal_unreachable" and result["roll"] is None
    assert after == before


def test_material_traits_checked_for_unseen_spear_and_wrong_material():
    spec = fresh_spec()
    spec["goal"] = "походное копьё"
    spec["parameters"].update(
        input_traits=["shaft"], required_traits=["shaft"], result_capabilities=["pointed_weapon"]
    )
    before = initial(rows_v2()[0], spec)
    after, result, _ = resolve(before, spec, high_seed())
    assert result["outcome"] == "best_possible"
    assert after["objects"]["subject"]["properties"]["capabilities"] == ["pointed_weapon"]
    before["objects"]["subject"]["properties"]["traits"] = ["fabric"]
    after, result, _ = resolve(before, spec, high_seed())
    assert result["outcome"] == "goal_unreachable" and after == before
    spec["parameters"]["required_tool_capabilities"] = ["steam"]
    before = initial(rows_v2()[0], spec)
    after, result, _ = resolve(before, spec, high_seed())
    assert result["blocker"] == "missing_tool_capability" and after == before


def test_unknown_spell_not_granted_by_knowing_a_different_spell():
    source = rows_v2()[10]  # Explicit magical profile, not an empty spell list.
    spec = deepcopy(specs()["magic:5"])
    spec["parameters"]["effect"] = "creates_real_gold"
    before = initial(source, spec)
    assert before["hero"]["known_effects"]
    after, result, _ = resolve(before, spec, high_seed())
    assert result["blocker"] == "unknown_effect" and after == before


def test_unknown_npc_authority_requires_clarification_before_rolling():
    spec = deepcopy(specs()["negotiation:1"])
    before = initial(rows_v2()[0], spec)
    before["npc"]["authority"] = None
    after, result, _ = resolve(before, spec, high_seed())
    assert result["outcome"] == "clarification_required" and result["goal_reachable"] is None
    assert not result["d20_required"] and after == before


def test_numeric_ledger_checker_is_independent_of_reference_target_text():
    source = rows_v2()[0]
    row = compile_row(source, specs()["bow_craft:0"])
    row["after_state"]["hero"]["gold"] += 1
    assert "MONEY_NOT_CONSERVED" in invariant_errors(row)
    row = compile_row(source, specs()["bow_craft:0"])
    row["engine_receipt"]["roll"]["total"] += 1
    assert "D20_ARITHMETIC_MISMATCH" in invariant_errors(row)
    row = compile_row(source, specs()["bow_craft:0"])
    row["after_state"]["world"]["food"] += 1
    assert "FOOD_NOT_CONSERVED" in invariant_errors(row)
    row["after_state"]["hero"]["level"] = 5
    assert "LEVEL_XP_MISMATCH" in invariant_errors(row)


def test_unsupported_primitive_never_silently_reports_success():
    spec = fresh_spec()
    before = initial(rows_v2()[0], spec)
    spec["operation"] = "grant_anything"
    with pytest.raises(ValueError, match="Unknown reference primitive"):
        resolve(before, spec, high_seed())


def test_workbook_contains_complete_states_and_blank_human_decisions(corpus, tmp_path):
    from training.grounded_workbook import export
    from training.xlsx import read

    folder, _ = corpus
    processed = tmp_path / "admitted"
    admit(folder, authorization(tmp_path / "owner.json"), processed)
    path = tmp_path / "review.xlsx"
    assert export(processed, path)["samples"] == 1100
    original = read(path, sheet="1000 сценариев")
    boundaries = read(path, sheet="100 границ правил")
    assert len(original) == 1001 and len(boundaries) == 101
    assert all(r["F"] and r["N"] and r["O"] and not r["Q"] for r in original[1:])
    assert json.loads(original[1]["F"])["hero"]["life"]["maximum"] > 0


def test_holdout_uses_training_prompt_without_target_leakage(corpus, tmp_path):
    from training.evaluate_faun import evaluate
    from training.tokenize_dataset import messages_for

    folder, _ = corpus
    processed = tmp_path / "admitted"
    admit(folder, authorization(tmp_path / "owner.json"), processed)
    _, parts = verify(processed)
    captured = []

    def requester(path, body=None):
        if path == "/api/tags":
            return {"models": [{"name": "dnd-base-narrator", "digest": "fixture", "size": 1}]}
        captured.append(body)
        return {"done": True, "message": {"content": "Состояние сохраняется."}}

    result = evaluate(
        processed, grounded_synthetic=True, model="dnd-base-narrator", limit=1, requester=requester
    )
    row = parts["test"][0]
    assert captured[0]["messages"] == messages_for(row)
    assert captured[0]["messages"][-1]["role"] == "user"
    assert row["assistant_reply"] not in json.dumps(captured[0], ensure_ascii=False)
    assert result["samples"][0]["prompt_sha256"] and result["human_review"] is None
