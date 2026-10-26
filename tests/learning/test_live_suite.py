import json
from decimal import Decimal

import pytest

from rpg_vkr.learning import live_suite as suite
from rpg_vkr.learning.library import build
from rpg_vkr.learning.live_probe import MODEL, request
from rpg_vkr.learning.probe_cases import PRIVATE_DIARY, PRIVATE_PLOT
from rpg_vkr.narrative.routerai import KeyAllowance, ModelQuote
from rpg_vkr.narrative.story_prompt import writing_profile


def test_real_probe_states_are_private_atomic_and_replayable_with_paired_budget(
    small_package, tmp_path, monkeypatch
):
    package, _ = small_package
    directory = tmp_path / "library"
    build(package, directory)
    jobs = suite.prepare(directory)
    assert len(jobs) == 48 and len({j["case"] for j in jobs}) == 24
    assert {j["mode"] for j in jobs} == {"B0", "B3"}
    for job in jobs:
        payload = json.dumps(job["local"], ensure_ascii=False)
        assert PRIVATE_DIARY not in payload and PRIVATE_PLOT not in payload
        assert suite.fingerprint(job["session"]) == job["before"]
        if job["case"] in ("craft_no_material", "craft_unknown", "spell_unknown"):
            assert job["context"]["obstacle"]
        if job["case"] in ("team_receipt", "spell_utility"):
            assert job["context"]["receipt"]["committed"]
            assert job["context"]["turn_brief"]["mode"] == "result"
    memory = next(j for j in jobs if j["case"] == "memory_100" and j["mode"] == "B3")
    assert memory["context"]["learning_memory"]
    actor = next(a for a in memory["session"].interaction_state().actor_refs if a.id == "scribe")
    assert actor.name == "Ливна"
    # Exercise the real shared reservation/concurrency without any HTTP calls.
    monkeypatch.setattr(suite, "prepare", lambda _: jobs[:4])
    quote = ModelQuote(MODEL, Decimal("0.00001"), Decimal("0.00002"), ("max_tokens",))
    monkeypatch.setattr(suite, "parse_models", lambda _: [quote])
    monkeypatch.setattr(
        suite, "parse_allowance", lambda _: KeyAllowance(Decimal(100), Decimal(0), Decimal(100))
    )
    posts = []

    def fake(url, *, key="", payload=None):
        if payload is None:
            return {}
        assert payload["model"] == MODEL
        posts.append(payload)
        return {
            "model": MODEL,
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "Площадь освещена солнцем. Ветер качает ветви.",
                    },
                }
            ],
        }

    monkeypatch.setattr(suite, "request", fake)
    report = suite.run("synthetic-key", directory, budget=Decimal(5))
    assert report["sent_generations"] == len(posts) == 4
    assert report["canonical_state_and_rng_unchanged"]
    assert Decimal(report["reserved_upper_rub"]) <= 5
    posts.clear()
    report = suite.run("synthetic-key", directory, budget=Decimal("0.001"))
    assert not posts and report["sent_generations"] == 0
    assert all(r["status"] == "SKIPPED_BUDGET" for r in report["rows"])


@pytest.mark.parametrize("budget", [Decimal("NaN"), Decimal("Infinity"), Decimal(0), Decimal(147)])
def test_suite_rejects_invalid_budget_before_network(tmp_path, monkeypatch, budget):
    monkeypatch.setattr(suite, "request", lambda *a, **k: pytest.fail("network forbidden"))
    with pytest.raises(ValueError):
        suite.run("synthetic-key", tmp_path, budget=budget)


def test_key_validation_does_not_expose_invalid_header_value():
    with pytest.raises(ValueError) as error:
        request("https://routerai.ru/api/v1/key", key="synthetic\nsecret")
    assert "synthetic" not in str(error.value) and "secret" not in str(error.value)


def test_flash41_reserves_reasoning_room_without_extending_requested_prose():
    old = writing_profile("~deepseek/deepseek-v4-flash-latest")
    new = writing_profile(MODEL)
    assert new["num_predict"] == 2048 and new["repair_predict"] == 3072
    assert old["num_predict"] == 900 and new["length"] == old["length"]
