"""Public object descriptions, persistent profiles and isolated image compositions. No APIs."""

import json
from dataclasses import replace

import pytest
from response_cases import new_session

from rpg_vkr.domain.adventure import MemoryNote
from rpg_vkr.domain.catalog import Definition, Entity, seed_catalog
from rpg_vkr.domain.interactions import Step, WorldPlan
from rpg_vkr.domain.object_descriptions import default_profiles
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.ollama import OllamaClient
from rpg_vkr.narrative.story import story_payload
from rpg_vkr.storage.campaigns import CampaignRepository
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.chronicles_panel import card_html
from rpg_vkr.ui.knowledge import knowledge_entries
from rpg_vkr.ui.main_window import MainWindow
from rpg_vkr.ui.narrator_panel import catalog_context
from rpg_vkr.visuals.context import entity_target, make_prompt, scene_target


def item(session, key):
    return next(e for e in knowledge_entries(session) if e.key == key)


def register_object(
    session, properties=None, *, id="prism", name="Трёхгранная печать", category="miscellaneous"
):
    session.register_catalog(
        "осматриваю находку",
        (Definition(id + "_type", name, "item", (category,), properties or {}),),
        (Entity(id, id + "_type", "landing"),),
        "Найдено в текущем месте",
        "test",
    )
    return item(session, id)


def remember_profile(session, fields, *, subject="prism", private=False):
    session.remember(
        [
            {
                "subject": subject,
                "kind": "knowledge",
                "text": json.dumps(
                    {"field": "object_profile", "value": fields}, ensure_ascii=False
                ),
                "importance": 3,
                "private": private,
            }
        ],
        "test:description",
    )


def test_bandage_has_shape_type_and_ordinary_purpose_without_revealing_healing_numbers():
    session = new_session()
    before = session.to_dict(), session.dice.checkpoint()
    bandage = next(e for e in knowledge_entries(session) if e.title == "Бинт")
    fields = dict(bandage.fields)
    assert fields["Тип предмета"] == "Перевязочный бинт"
    assert "рулон" in fields["Внешний вид"] and "Перевязка" in fields["Назначение"]
    assert "Ткань" in fields["Материал"]
    assert "100" not in card_html(bandage) and "heal" not in card_html(bandage)
    target = entity_target(session, bandage)
    assert fields["Внешний вид"] in target.brief and fields["Назначение"] in target.brief
    assert before == (session.to_dict(), session.dice.checkpoint())


def test_all_authored_types_have_basic_profiles_without_rewriting_seed_data():
    required = {d.id for d in seed_catalog().definitions if d.kind != "actor"}
    assert required <= default_profiles().keys()
    assert all(
        {"object_type", "appearance", "purpose"} <= default_profiles()[id].keys() for id in required
    )
    assert all("public_appearance" not in d.properties for d in seed_catalog().definitions)


def test_unknown_item_does_not_reveal_secret_type_material_effect_or_true_purpose():
    session = new_session()
    entry = register_object(
        session,
        {
            "unidentified": True,
            "appearance": "SECRET-TRUE-SHAPE",
            "purpose": "SECRET-NECROMANCY",
            "material": "SECRET-METAL",
            "effects": "SECRET-POWER",
            "public_appearance": "Матовое кольцо с тремя гранями",
        },
        name="SECRET-TRUE-NAME",
    )
    text = json.dumps(entry.public_dict(session.campaign.world_id), ensure_ascii=False)
    prompt = make_prompt(entity_target(session, entry), [])
    assert "Матовое кольцо" in text and "Неопознанный предмет" in text
    assert "SECRET" not in text and "SECRET" not in prompt
    assert "SECRET" not in entry.title


def test_arbitrary_new_object_profile_is_saved_once_and_shared_with_artist_and_master(tmp_path):
    session = new_session()
    register_object(session)
    fields = {
        "object_type": "Керамическая печать",
        "appearance": "Три матовые грани и короткая рукоятка",
        "purpose": "Оставлять оттиск на мягком воске",
        "material": "Керамика",
    }
    remember_profile(session, fields)
    remember_profile(session, {"appearance": "ДРУГАЯ ВНЕШНОСТЬ"})
    expected = item(session, "prism")
    assert fields["appearance"] in expected.description and "ДРУГАЯ" not in expected.search_text
    prompt = make_prompt(entity_target(session, expected), [])
    assert all(v in prompt for v in fields.values())
    slots = SaveSlots(tmp_path / "saves")
    slots.save(1, session)
    restored = slots.load(1)
    assert item(restored, "prism") == expected
    db = CampaignRepository(tmp_path / "campaigns.sqlite3")
    db.sync(session)
    assert item(db.load(db.identity(session)), "prism") == expected
    public = campaign_context(restored)["public_objects"]
    assert any(
        row["id"] == "prism" and fields["appearance"] in row["description"] for row in public
    )


def test_existing_canonical_appearance_wins_over_a_conflicting_profile():
    session = new_session()
    register_object(
        session, {"public_appearance": "Синяя керамика", "public_object_type": "Печать"}
    )
    remember_profile(session, {"appearance": "Красное стекло", "purpose": "Ставить оттиск"})
    entry = item(session, "prism")
    assert "Синяя керамика" in entry.description and "Красное стекло" not in entry.search_text
    assert "Ставить оттиск" in dict(entry.fields)["Назначение"]


def test_private_profile_and_unknown_fields_do_not_enter_card_or_image():
    session = new_session()
    register_object(session)
    remember_profile(session, {"appearance": "PRIVATE-APPEARANCE"}, private=True)
    remember_profile(session, {"appearance": "MALFORMED-PROFILE", "gold": "SECRET-GOLD"})
    entry = item(session, "prism")
    assert "PRIVATE" not in entry.search_text and "SECRET" not in entry.search_text
    assert "MALFORMED" not in make_prompt(entity_target(session, entry), [])


def test_observed_object_keeps_appearance_after_leaving_and_no_live_remote_changes_leak():
    session = new_session()
    register_object(session, {"public_appearance": "Три матовые грани"})
    remember_profile(session, {"object_type": "Печать", "purpose": "Оттиск на воске"})
    session.submit_interaction("ухожу в галерею", WorldPlan((Step("move", "gallery"),)))
    entities = tuple(
        replace(e, state={"public_appearance": "SECRET-REMOTE-CHANGE"}) if e.id == "prism" else e
        for e in session.catalog.entities
    )
    session.catalog = replace(session.catalog, entities=entities)
    entry = item(session, "prism")
    assert not entry.here and "SECRET" not in entry.search_text
    assert "Три матовые грани" in entry.description


@pytest.mark.parametrize(
    "category", ["medicine", "weapons", "armour", "materials", "plants", "miscellaneous"]
)
def test_any_item_category_uses_an_isolated_object_composition(category):
    session = new_session()
    entry = register_object(
        session,
        {
            "public_object_type": "Складной инструмент",
            "public_appearance": "Три соединённых секции",
            "public_purpose": "Работа с древесиной",
        },
        category=category,
    )
    target = entity_target(session, entry)
    prompt = make_prompt(target, [{"caption": "Складной инструмент"}])
    assert "SINGLE OBJECT STUDY" in prompt and "No people" in prompt
    assert "extract ONLY" in prompt and "purpose" in prompt.lower()
    assert "Складной инструмент" in prompt and "Три соединённых секции" in prompt


def test_scene_composition_still_allows_confirmed_characters():
    session = new_session()
    prompt = make_prompt(scene_target(session), [])
    assert "EVENT OR SCENE" in prompt and "No people" not in prompt
    npc = next(e for e in knowledge_entries(session) if e.category == "people")
    assert "PORTRAIT" in make_prompt(entity_target(session, npc), [])


def test_existing_appearance_memory_is_used_without_parsing_literary_dialogue():
    session = new_session()
    register_object(session)
    session.chronicle = session.chronicle.remember(
        (
            MemoryNote(
                "prism", "appearance", "Три серые грани", 3, False, len(session.turns), "test"
            ),
        )
    )
    assert "Три серые грани" in item(session, "prism").description


def test_description_context_and_prompts_use_existing_requests_only(qt_app, tmp_path, monkeypatch):
    session = new_session()
    register_object(session)
    window = MainWindow(session=session, saves=SaveSlots(tmp_path / "saves"))
    window._confirm = lambda *_: True
    try:
        state = catalog_context(window, "опиши печать")
        assert any(row["id"] == "prism" for row in state["description_requests"])
        assert len(state["description_requests"]) <= 3 and len(state["public_objects"]) <= 12
        client = OllamaClient()
        client.models = ["test"]
        calls = []
        monkeypatch.setattr(client, "_start", lambda path, kind, body: calls.append((kind, body)))
        frame = build_frame(session)
        client.plan_world(frame, "test", "опиши печать", state)
        assert len(calls) == 1 and "object_profile" in calls[0][1]["messages"][0]["content"]
        assert "public_appearance" in calls[0][1]["messages"][0]["content"]
        client.generate_world(frame, "test", {})
        assert len(calls) == 2 and "public_object_type" in calls[-1][1]["messages"][0]["content"]
        payload = story_payload(frame, "test", "опиши печать", campaign=campaign_context(session))
        assert "Трёхгранная печать" in json.dumps(payload, ensure_ascii=False)
    finally:
        window.close()


def test_description_button_prepares_input_without_network_or_losing_a_draft(qt_app, tmp_path):
    session = new_session()
    register_object(session)
    window = MainWindow(session=session, saves=SaveSlots(tmp_path / "saves"))
    window._confirm = lambda *_: True
    before = session.to_dict(), session.dice.checkpoint()
    try:
        panel = window.chronicles_panel
        panel.open_entry("prism")
        panel.describe_button.click()
        assert "Трёхгранная печать" in window.action_input.text()
        assert "Сохрани описание" in window.action_input.text()
        window.action_input.setText("Неотправленная реплика")
        panel.describe_button.click()
        assert window.action_input.text() == "Неотправленная реплика"
        assert before == (session.to_dict(), session.dice.checkpoint())
        assert not window.visuals.worker.busy and not window.ollama.busy
    finally:
        window.close()


def test_inline_master_reply_persists_object_profile_in_one_model_post(
    window, qt_app, monkeypatch, tmp_path
):
    from test_local_narrator import wait_for
    from test_routerai import configure, router_server

    window._session = new_session()
    register_object(window._session)
    message = "Мастер, опиши печать подробно"
    profile = {
        "object_type": "Керамическая печать",
        "appearance": "Три матовые грани и короткая рукоять",
        "purpose": "Оставлять оттиск на воске",
    }
    plan = {
        "steps": [],
        "places": [],
        "check": "none",
        "dialogue_target": "",
        "reply": "У печати три матовые грани и короткая рукоять. Ею оставляют оттиск на воске.",
        "memories": [
            {
                "subject": "prism",
                "kind": "knowledge",
                "text": json.dumps(
                    {"field": "object_profile", "value": profile}, ensure_ascii=False
                ),
                "importance": 3,
                "private": False,
            }
        ],
    }
    before = window._session.world, window._session.dice.checkpoint()
    with router_server(world_plans={message: plan}) as (url, calls):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        window.action_input.setText(message)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len([c for c in calls if c["method"] == "POST"]) == 1
        entry = item(window._session, "prism")
        assert profile["appearance"] in entry.description
        assert profile["purpose"] in dict(entry.fields)["Назначение"]
        assert before == (window._session.world, window._session.dice.checkpoint())
        slots = SaveSlots(tmp_path / "profile-save")
        slots.save(1, window._session)
        restored = slots.load(1)
        assert entry == item(restored, "prism")
        assert profile["appearance"] in make_prompt(
            entity_target(restored, item(restored, "prism")), []
        )


def test_distinct_instance_profiles_do_not_share_a_type_image():
    session = new_session()
    register_object(session)
    session.register_catalog(
        "замечаю вторую печать",
        (),
        (Entity("prism_two", "prism_type", "landing"),),
        "Вторая печать лежит рядом",
        "test",
    )
    remember_profile(session, {"appearance": "Серебристая поверхность с тремя рёбрами"})
    remember_profile(
        session, {"appearance": "Чёрная матовая поверхность с кольцом"}, subject="prism_two"
    )
    first = entity_target(session, item(session, "prism"), shared=True)
    second = entity_target(session, item(session, "prism_two"), shared=True)
    assert first.subject != second.subject and not first.common and not second.common
    assert first.economy_eligible and second.economy_eligible
    assert "Чёрная" not in first.brief and "Серебристая" not in second.brief
