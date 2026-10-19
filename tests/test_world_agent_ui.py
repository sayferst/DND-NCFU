"""The actual chat applies a world transaction before any literary response."""

import json

from test_local_narrator import wait_for
from test_routerai import configure, router_server
from test_world_transactions import escape_plan

from rpg_vkr.application import Session
from rpg_vkr.domain.interactions import Step, WorldPlan
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.main_window import MainWindow

TAKE = "молча беру корзину с яблоками и убегаю прочь от неё в сторону леса"
EMPTY = "забираю все яблоки из корзины, а корзину выкидываю возле тропы"
WRITER = "Ветер шелестит в ветвях. На лесной тропе становится тише; деревня осталась позади."


def envelope(plan):
    return json.loads(json.dumps(plan.to_dict())) | {"check": "none"}


def test_live_ui_enables_the_world_agent_without_starting_network(qt_app, tmp_path, monkeypatch):
    window = MainWindow(session=Session(seed=5), saves=SaveSlots(tmp_path))
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    try:
        assert window.world_agent.isChecked()
        assert not window.ollama.busy and window.ollama.cloud is None
    finally:
        window.close()


def test_user_sequence_in_chat_changes_real_inventory_location_and_npc_attitude(
    window, qt_app, monkeypatch
):
    window._session = Session(seed=5)
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    plans = {
        TAKE: envelope(escape_plan()),
        EMPTY: envelope(
            WorldPlan(
                (
                    Step("take", "apples", 0),
                    Step("drop", "produce_basket"),
                )
            )
        ),
    }
    with router_server(world_plans=plans, writer_text=WRITER) as (url, records):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        window.director_mode.setChecked(True)
        for i, text in enumerate((TAKE, EMPTY), 1):
            window.action_input.setText(text)
            window.send_button.click()
            wait_for(
                qt_app,
                lambda count=i: not window.ollama.busy and len(window._session.narrations) == count,
            )
        s = window._session
        assert s.current_place_id == "forest"
        assert s.combat.actor("villager").disposition == "hostile"
        assert s.combat.actor("guard").disposition == "hostile"
        assert build_frame(s).visible_actors == ()
        assert [(t.id, t.quantity) for t in s.interactive_world.carried()] == [("apples", 12)]
        assert window.scene_title.text() == "Лесная тропа"
        rows = [
            [window.inventory_table.item(r, c).text() for c in range(3)]
            for r in range(window.inventory_table.rowCount())
        ]
        assert any(row[:2] == ["Яблоки", "12"] for row in rows)
        calls = len(records)
        before = s.dice.checkpoint()
        window.action_input.setText("осмотреть свой инвентарь")
        window.send_button.click()
        assert "Яблоки ×12" in window.journal.toPlainText()
        assert len(records) == calls and s.dice.checkpoint() == before
        window.save_slot(1)
        window.load_slot(1)
        assert window._session.to_dict() == s.to_dict()
        assert window._session.current_place_id == "forest"
        assert len([r for r in records if r["method"] == "POST"]) == 4


def test_bad_writer_does_not_roll_back_executed_actions_or_reroll(window, qt_app, monkeypatch):
    window._session = Session(seed=5)
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    with router_server(world_plans={TAKE: envelope(escape_plan())}, writer_text="走近") as (
        url,
        records,
    ):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        window.director_mode.setChecked(True)
        window.action_input.setText(TAKE)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert len(window._session.turns) == 1
        assert window._session.turns[0].interaction
        assert window._session.current_place_id == "forest"
        assert window._session.dice.checkpoint()[1] == 1
        assert (
            "Яблоки" in window.inventory_table.item(2, 0).text()
            or "Яблоки" in build_frame(window._session).inventory
        )
        assert not window.action_input.text()
        assert len([r for r in records if r["method"] == "POST"]) == 3


def test_cancelled_risk_keeps_the_whole_input_and_performs_no_transaction(
    window, qt_app, monkeypatch
):
    window._session = Session(seed=5)
    monkeypatch.setattr(window, "_confirm", lambda _: False)
    before = window._session.to_dict(), window._session.dice.checkpoint()
    with router_server(world_plans={TAKE: envelope(escape_plan())}, writer_text=WRITER) as (
        url,
        records,
    ):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        window.action_input.setText(TAKE)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
        assert window.action_input.text() == TAKE
        assert len([r for r in records if r["method"] == "POST"]) == 1


def test_invalid_second_step_cannot_apply_the_first_step(window, qt_app, monkeypatch):
    window._session = Session(seed=5)
    before = window._session.to_dict(), window._session.dice.checkpoint()
    bad = envelope(WorldPlan((Step("take", "produce_basket"), Step("move", "unknown"))))
    with router_server(world_plans={TAKE: bad}) as (url, records):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        window.action_input.setText(TAKE)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
        assert window.action_input.text() == TAKE
        assert len([r for r in records if r["method"] == "POST"]) == 1


def test_empty_model_plan_cannot_turn_a_transfer_into_uncommitted_prose(
    window, qt_app, monkeypatch
):
    window._session = Session(seed=5)
    before = window._session.to_dict(), window._session.dice.checkpoint()
    with router_server(world_plans={}, writer_text=WRITER) as (url, records):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        window.action_input.setText(TAKE)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert (window._session.to_dict(), window._session.dice.checkpoint()) == before
        assert window.action_input.text() == TAKE
        assert "не составил план" in window.narrator_status.text()
        assert len([r for r in records if r["method"] == "POST"]) == 1


def test_world_agent_dialogue_stays_dialogue_without_item_transfers(window, qt_app, monkeypatch):
    text = "Что видно вдали за деревней?"
    with router_server(
        world_plans={},
        writer_text="Вдали над холмами висит лёгкая дымка. Дорога теряется между ними.",
    ) as (url, records):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        window.director_mode.setChecked(True)
        window.action_input.setText(text)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert window._session.turns[-1].scene
        assert window._session.interactive_world is None
        assert len([r for r in records if r["method"] == "POST"]) == 2


def test_unfamiliar_wording_shows_plan_for_confirmation_instead_of_requiring_a_command(
    window, qt_app, monkeypatch
):
    window._session = Session(seed=5)
    questions = []
    monkeypatch.setattr(window, "_confirm", lambda question: questions.append(question) or False)
    text = "Присвою корзину с плодами"
    plan = envelope(WorldPlan((Step("take", "produce_basket"),)))
    with router_server(world_plans={text: plan}) as (url, records):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        window.action_input.setText(text)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert questions and "Плетёная корзина" in questions[-1]
        assert window._session.turns == ()
        assert window.action_input.text() == text
        assert len([r for r in records if r["method"] == "POST"]) == 1
