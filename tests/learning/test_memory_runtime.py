"""Long histories, knowledge scopes and the actual narrator payload, without inference."""

from copy import deepcopy

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.catalog import Definition, Entity
from rpg_vkr.domain.interactions import Step, WorldPlan
from rpg_vkr.learning.library import active_path, build
from rpg_vkr.learning.memory import recall
from rpg_vkr.learning.runtime import enrich
from rpg_vkr.learning.settings import load, update
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.story import story_context, story_payload, validate_story_text
from rpg_vkr.narrative.story_prompt import render_context
from rpg_vkr.storage.campaigns import CampaignRepository
from rpg_vkr.storage.slots import SaveSlots


def register_person(session):
    session.register_catalog(
        "Замечаю нового мастера Эйру у кузницы",
        [Definition("eyra_type", "Эйра", "actor", ("npcs",), {"hp_max": 10})],
        [Entity("eyra", "eyra_type", "square", state={"hp": 10})],
        "Встреча в текущем месте",
        "own-offline-fixture",
    )


def test_npc_and_committed_memory_survive_10_50_100_turns_and_both_storage_paths(
    learning_session, tmp_path
):
    session = learning_session
    register_person(session)
    first_id = recall(session, "Эйра")[0]["event_id"]
    for number in range(1, 101):
        session.perform_gameplay("wait", {"minutes": 1}, "memory_" + str(number))
        if number in (10, 50, 100):
            found = recall(session, "Эйра")
            assert found and found[0]["event_id"] == first_id
            restored = Session.from_dict(deepcopy(session.to_dict()), version=28)
            assert recall(restored, "Эйра")[0]["event_id"] == first_id
            assert (
                next(a.name for a in restored.interaction_state().actor_refs if a.id == "eyra")
                == "Эйра"
            )
    slots = SaveSlots(tmp_path / "slots")
    slots.save(1, session)
    assert recall(slots.load(1), "Эйра")[0]["event_id"] == first_id
    repository = CampaignRepository(tmp_path / "memory.sqlite3")
    repository.sync(session)
    other = repository.load(repository.identity(session))
    assert recall(other, "Эйра")[0]["event_id"] == first_id


def test_world_hero_scopes_and_npc_observation_are_enforced(learning_session, new_session_factory):
    new_session = new_session_factory
    session = learning_session
    session.submit_interaction(
        "осматриваю выставочный меч", WorldPlan((Step("look", "display_blade"),))
    )
    session.write_diary("Личный секрет", "ПРИВАТНЫЙ_ДНЕВНИК", pinned=True)
    before = session.to_dict(), session.dice.checkpoint()
    assert recall(session, "меч", npc_id="witness")
    assert not recall(session, "меч", npc_id="distant")
    assert not recall(session, "ПРИВАТНЫЙ_ДНЕВНИК")
    assert not recall(session, "СКРЫТАЯ_МЕТКА")
    second = new_session(world_id=session.campaign.world_id)
    assert second.campaign.hero_id != session.campaign.hero_id
    assert second.catalog.to_dict() == session.chronicle.seed.catalog.to_dict()
    assert not recall(second, "меч")  # Shared initial canon does not share private experience.
    with pytest.raises(ValueError):
        recall(session, "меч", expected_hero_id=second.campaign.hero_id)
    with pytest.raises(ValueError):
        recall(session, "меч", expected_world_id=new_session().campaign.world_id)
    assert (session.to_dict(), session.dice.checkpoint()) == before


def test_reviewed_rag_and_memory_reach_payload_while_shadow_does_not_change_prompt(
    learning_session, small_package, tmp_path, monkeypatch
):
    from rpg_vkr.learning import runtime

    source, _ = small_package
    directory = tmp_path / "library"
    build(source, directory)
    monkeypatch.setattr(runtime, "active_path", lambda d: active_path(d or directory))
    session = learning_session
    register_person(session)
    session._learning_flags = {"library": True, "memory": True}
    session._rag_mode = 2
    query = "Мастер, помню Эйру, осматриваю меч"
    campaign = campaign_context(session, query=query)
    before = session.to_dict(), session.dice.checkpoint()
    context = story_context(build_frame(session), "deepseek/model", query, campaign=campaign)
    payload = story_payload(build_frame(session), "deepseek/model", query, context=context)
    assert context["learning_trace"]["sources"]
    assert context["learning_trace"]["extra_bytes"] <= 1800
    assert "past_confirmed_event" in payload["messages"][1]["content"]
    assert "PROJECT-METHODS-2" in payload["messages"][1]["content"]
    assert (session.to_dict(), session.dice.checkpoint()) == before
    base = story_context(build_frame(session), "deepseek/model", query)
    shadow = enrich(deepcopy(base), query, {"library": True, "mode": 1}, directory=directory)
    assert shadow["learning_trace"]["sources"]
    assert render_context(shadow) == render_context(base)
    assert (
        enrich(base, query, {"library": True, "mode": 2}, directory=tmp_path / "missing")[
            "learning_trace"
        ]["status"]
        == "baseline_fallback"
    )


def test_flags_are_off_and_updates_preserve_existing_preferences(tmp_path):
    path = tmp_path / "learning.json"
    assert load(path) == {"mode": 0, "library": False, "memory": False, "templates": False}
    path.write_text('{"mode":2,"other":"keep"}', encoding="utf-8")
    update({"library": True}, path)
    update({"mode": 1}, path)
    assert load(path)["library"] and load(path)["mode"] == 1
    assert '"other":"keep"' in path.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        update({"memory": 1}, path)


def test_known_metaphors_remain_valid_and_inspection_is_not_purchase(learning_session):
    session = learning_session
    initial = session.world.gold, session.gameplay["copper"], session.dice.checkpoint()
    session.submit_interaction(
        "осматриваю меч, покупать не буду", WorldPlan((Step("look", "display_blade"),))
    )
    assert (
        next(t.owner for t in session.interaction_state().things if t.id == "display_blade")
        == "witness"
    )
    assert (session.world.gold, session.gameplay["copper"], session.dice.checkpoint()) == initial
    before = session.to_dict()
    for text in (
        "Вы получили ответ. Мёртвая тишина нависает над площадью.",
        "С рассвета ломит спину. Слева слышен звон молотка.",
    ):
        validate_story_text(text)
    assert session.to_dict() == before
