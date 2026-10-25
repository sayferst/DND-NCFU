"""Public knowledge, histories, exports and campaign isolation; no actual model requests."""

import json
from copy import deepcopy
from dataclasses import replace

from PySide6.QtCore import QEvent
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QFileDialog, QToolTip
from response_cases import new_session

from rpg_vkr.application import Session
from rpg_vkr.domain.adventure import MemoryNote
from rpg_vkr.domain.catalog import Definition, Entity
from rpg_vkr.domain.interactions import Step, WorldPlan
from rpg_vkr.storage.campaigns import CampaignRepository
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.chronicles_panel import card_html
from rpg_vkr.ui.knowledge import knowledge_entries
from rpg_vkr.ui.main_window import MainWindow


def learn(session, field, value, *, subject="vesta", private=False, kind="knowledge"):
    note = MemoryNote(
        subject,
        kind,
        json.dumps({"field": field, "value": value}, ensure_ascii=False),
        3,
        private,
        len(session.turns),
        "test:public-revelation",
    )
    session.chronicle = session.chronicle.remember((note,))


def public_text(session):
    return json.dumps(
        [e.public_dict(session.campaign.world_id) for e in knowledge_entries(session)],
        ensure_ascii=False,
    )


def test_no_canonical_name_wallet_goals_or_hidden_places_leak():
    session = new_session()
    entities = list(session.catalog.entities)
    e = next(e for e in entities if e.id == "vesta")
    entities[entities.index(e)] = replace(
        e, state=(e.state or {}) | {"gold_cp": 987654, "secret": "HIDDEN-SPY"}
    )
    session.catalog = replace(session.catalog, entities=tuple(entities))
    before = deepcopy(session.to_dict()), session.dice.checkpoint()
    text = public_text(session)
    assert "Веста" not in text and "987654" not in text and "HIDDEN-SPY" not in text
    assert "Галерея" not in text and '"key"' not in text and "token" not in text
    assert (session.to_dict(), session.dice.checkpoint()) == before


def test_structured_revelation_updates_any_npc_without_prose_parsing():
    session = new_session()
    learn(session, "public_name", "Веста")
    learn(session, "role", "Картограф речных путей")
    learn(session, "background", "Служила в порту", private=True)
    record = next(e for e in knowledge_entries(session) if e.key == "vesta")
    assert record.title == "Веста" and "картограф" in record.search_text
    assert "Служила" not in public_text(session)


def test_rumour_is_distinct_and_unknown_structured_fields_are_not_rendered():
    session = new_session()
    note = MemoryNote(
        "vesta", "rumour", "Говорят, она ищет потерянную гавань.", 2, False, 0, "test"
    )
    unsafe = MemoryNote(
        "vesta", "knowledge", '{"field":"secret","value":"HIDDEN-SECRET"}', 2, False, 0, "test"
    )
    session.chronicle = session.chronicle.remember((note, unsafe))
    entry = next(e for e in knowledge_entries(session) if e.key == "vesta")
    assert entry.rumour and "Слух" in card_html(entry)
    assert "HIDDEN-SECRET" not in public_text(session)


def test_factions_come_only_from_real_public_knowledge():
    session = new_session()
    assert not any(e.category == "factions" for e in knowledge_entries(session))
    learn(session, "faction", "Гильдия картографов")
    faction = next(e for e in knowledge_entries(session) if e.category == "factions")
    assert faction.title == "Гильдия картографов"


def test_hidden_inventory_and_closed_containers_do_not_become_known():
    session = new_session()
    defs = (
        Definition(
            "hidden_box_type",
            "Шкатулка",
            "item",
            ("miscellaneous",),
            {"container": True, "open": False},
        ),
        Definition("hidden_scroll_type", "СВИТОК-В-ТАЙНИКЕ", "item", ("miscellaneous",), {}),
    )
    entities = (
        Entity("hidden_box", "hidden_box_type", "landing"),
        Entity("hidden_scroll", "hidden_scroll_type", "hidden_box"),
    )
    session.register_catalog("осмотреть ящик", defs, entities, "Ящик у моста", "test")
    text = public_text(session)
    assert "Шкатулка" in text and "СВИТОК-В-ТАЙНИКЕ" not in text
    assert "Медный жетон" not in text  # Vesta's private carried item.


def test_old_npc_stays_at_last_seen_place_and_does_not_become_a_live_remote_feed():
    session = new_session()
    learn(session, "public_name", "Веста")
    session.submit_interaction("иду в галерею", WorldPlan((Step("move", "gallery"),)))
    entry = next(e for e in knowledge_entries(session) if e.key == "vesta")
    assert not entry.here
    assert ("Последнее известное место", "Мост над рекой") in entry.fields
    assert any(e.category == "places" and e.key == "gallery" for e in knowledge_entries(session))


def test_view_is_reconstructed_identically_from_slot_and_database(tmp_path):
    session = new_session()
    learn(session, "public_name", "Веста")
    learn(session, "role", "Картограф")
    expected = knowledge_entries(session)
    slots = SaveSlots(tmp_path / "saves")
    slots.save(1, session)
    assert knowledge_entries(slots.load(1)) == expected
    database = CampaignRepository(tmp_path / "campaigns.sqlite3")
    database.sync(session)
    assert knowledge_entries(database.load(database.identity(session))) == expected


def test_plain_literary_text_never_creates_a_known_entity_or_fact():
    from rpg_vkr.domain.director import Proposal

    session = new_session()
    before = knowledge_entries(session)
    session.submit_scene(
        "послушаю",
        Proposal("", "", "За рекой вспоминают тайного короля Ардена.", ()),
        "test",
        base_turn=0,
    )
    text = public_text(session)
    assert "Арден" not in text
    assert {e.key for e in before} == {e.key for e in knowledge_entries(session)}


def test_zero_quantity_items_and_unseen_catalog_types_are_not_demo_entries():
    text = public_text(Session())
    assert "Корзина поручения" not in text and "Обсидиан" not in text


def test_cards_escape_markup_and_bound_hover_content():
    session = new_session()
    learn(session, "role", "<script>unsafe</script>")
    entry = next(e for e in knowledge_entries(session) if e.key == "vesta")
    assert "<script>" not in card_html(entry) and "&lt;script&gt;" in card_html(entry)
    assert len(card_html(entry, True)) < 1800


def test_modern_codex_search_keyboard_tooltip_and_campaign_switch(qt_app, tmp_path, monkeypatch):
    session = new_session()
    learn(session, "public_name", "Веста")
    learn(session, "role", "Картограф")
    window = MainWindow(session=session, saves=SaveSlots(tmp_path / "saves"))
    window.show()
    window.resize(1280, 800)
    window.open_section("Хроники мира")
    qt_app.processEvents()
    panel = window.chronicles_panel
    try:
        panel.search.setText("картограф")
        assert panel.list.count() == 1 and "Веста" in panel.detail.toPlainText()
        # An actual tooltip event travels through the viewport.
        calls = []
        monkeypatch.setattr(QToolTip, "showText", lambda *args: calls.append(args))
        point = panel.list.visualItemRect(panel.list.item(0)).center()
        event = QHelpEvent(QEvent.Type.ToolTip, point, panel.list.viewport().mapToGlobal(point))
        qt_app.sendEvent(panel.list.viewport(), event)
        assert calls and "Веста" in calls[0][1]
        window._session = Session(seed=3)
        window._refresh_character()
        assert not panel.search.text() and "Веста" not in panel.detail.toPlainText()
        assert all(e.key != "vesta" for e in panel.entries)
    finally:
        window.close()


def test_public_export_cannot_overwrite_saves_or_reveal_secrets(qt_app, tmp_path, monkeypatch):
    session = new_session()
    learn(session, "public_name", "Веста")
    window = MainWindow(session=session, saves=SaveSlots(tmp_path / "saves"))
    try:
        path = tmp_path / "chronicles.json"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(path), "JSON"))
        window.chronicles_panel.export()
        exported = path.read_text(encoding="utf-8")
        assert "Веста" in exported and "gold_cp" not in exported and "private_plot" not in exported
        before = path.read_bytes()
        window.chronicles_panel.export()
        assert path.read_bytes() == before
        assert "не перезаписываются" in window.chronicles_panel.status.text()
    finally:
        window.close()


def test_export_cannot_create_a_fake_game_slot(qt_app, tmp_path, monkeypatch):
    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    path = window._saves.directory / "slot-1.json"
    window._saves.directory.mkdir(exist_ok=True)
    try:
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(path), "JSON"))
        window.chronicles_panel.export()
        assert not path.exists()
        assert "вне папки" in window.chronicles_panel.status.text()
    finally:
        window.close()


def test_heard_about_remote_npc_does_not_reveal_unobserved_appearance():
    session = new_session()
    from rpg_vkr.domain.interactions import ActorRef

    seed = session.chronicle.seed
    definition = Definition(
        "stranger_type",
        "SECRET-TRUE-NAME",
        "actor",
        ("npcs",),
        {"hp_max": 10, "appearance": "SECRET-UNSEEN-APPEARANCE"},
    )
    catalog = replace(
        seed.catalog,
        definitions=seed.catalog.definitions + (definition,),
        entities=seed.catalog.entities
        + (Entity("remote_stranger", "stranger_type", "gallery", state={"hp": 10}),),
    )
    scene = replace(
        seed.scene,
        actors=seed.scene.actors + (ActorRef("remote_stranger", "SECRET-TRUE-NAME", "gallery"),),
    )
    session.catalog, session.interactive_world = catalog, scene
    session.chronicle = replace(session.chronicle, seed=replace(seed, catalog=catalog, scene=scene))
    # A new hero has never encountered this particular person at the bridge.
    learn(session, "public_name", "Орин", subject="remote_stranger")
    text = public_text(session)
    assert "Орин" in text
    assert "SECRET-TRUE-NAME" not in text and "SECRET-UNSEEN-APPEARANCE" not in text
