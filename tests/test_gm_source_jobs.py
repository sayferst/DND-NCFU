"""Source resumes, materialization and selection preserve the actual input identity."""

import json

import pytest

from training.gm_source_pool import bind_job, identity, materialize_context
from training.select_gm_curriculum import context_contains, diversified
from training.source_gm_curation import crd3_context, grounding_screen


def test_pool_resume_requires_the_same_sources_and_policy(tmp_path):
    binding = {"curation_version": "v3", "source_sha256": "abc"}
    bind_job(tmp_path, binding, resume=False)
    bind_job(tmp_path, binding, resume=True)
    with pytest.raises(ValueError, match="differs"):
        bind_job(tmp_path, binding | {"source_sha256": "changed"}, resume=True)
    assert json.loads((tmp_path / "job.json").read_text(encoding="utf-8")) == binding


def test_unbound_legacy_cache_cannot_silently_resume(tmp_path):
    (tmp_path / "pool.sqlite").touch()
    with pytest.raises(ValueError, match="unbound"):
        bind_job(tmp_path, {"version": 3}, resume=True)


def test_deferred_crd3_materialization_is_checked_against_source_and_prefix():
    turns = [
        {"NAMES": ["LAURA"], "UTTERANCES": ["I inspect the doorway."]},
        {"NAMES": ["MATT"], "UTTERANCES": ["The door is open. A faint light flickers inside."]},
    ]
    text = " ".join(turns[1]["UTTERANCES"])
    context = crd3_context(turns, 1)
    left = len("The door is open.")
    context["earlier_same_source_utterance"] = text[:left]
    proof = {
        "file": "episode",
        "turn_index": 1,
        "source_text_sha256": identity(text),
        "normalized_span": [left, len(text)],
        "context_sha256": identity(context),
    }

    class Episodes:
        def load(self, path):
            assert path == "episode"
            return {"TURNS": turns}

    deferred = {"materialization": "CRD3_CONTEXT_FROM_PINNED_EPISODE"}
    assert materialize_context(deferred, proof, Episodes()) == context
    turns[0]["UTTERANCES"] = ["CHANGED_PREFIX"]
    with pytest.raises(ValueError, match="context differs"):
        materialize_context(deferred, proof, Episodes())


def test_target_leakage_is_detected_in_strings_not_only_json_rendering():
    assert context_contains({"text": 'He says "welcome" to you.'}, 'He says "welcome" to you.')
    assert not context_contains({"text": "Before the scene."}, "Unseen future")


def test_selection_keeps_episode_diversity_and_budget():
    rows = [("a", "one", {"repair": "mention"}), ("b", "two", {}), ("c", "one", {})]
    chosen = diversified(rows, 2)
    assert "a" in chosen and len(chosen) == 2
    assert diversified(rows, 0) == set()


def test_finishing_someone_off_is_not_licensed_by_living_or_zero_hp():
    assert (
        grounding_screen(
            "Karli finishes him off for good", {"targets_after": [{"hp": "<10/20 HP; Injured>"}]}
        )
        == "DEATH_CLAIM_WITH_CONFIRMED_SURVIVING_TARGETS"
    )
    assert (
        grounding_screen("The creature is dead.", {"targets_after": [{"hp": "<0/20 HP; Down>"}]})
        == "DEATH_CLAIM_REQUIRES_EXPLICIT_DEATH_EVIDENCE"
    )
