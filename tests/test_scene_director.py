"""New master proposals, memory selection, manual bridge and game-theory reference cases."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from rpg_vkr.application import Session
from rpg_vkr.domain.conflict import analyse_game, peaceful_contact
from rpg_vkr.domain.director import Proposal, StoryFact
from rpg_vkr.domain.memory import WorldMemory
from rpg_vkr.storage.knowledge import CampaignIndex, export_session, restore_session, retrieve
from rpg_vkr.storage.slots import SaveSlots

TEXT = (
    "Путник движется к шуму площади. Стражник отступает от створки ворот, "
    "оставляя проход свободным. «На площади готовятся к торгу. Вы туда по делу?»"
)
FACT = StoryFact("gate", "sensory_detail", "Гул доносится с площади, где готовятся к торгу.")


def proposal(*, focus="guard", facts=(FACT,), text=TEXT):
    return Proposal("", focus, text, facts)


def commit(session, value=None, text="пойду узнаю, что за знакомый гул"):
    return session.submit_scene(
        text, value or proposal(), "test-master:1", base_turn=len(session.turns)
    )


def test_free_scene_advances_from_reference_without_mechanical_side_effects(tmp_path):
    session = Session(seed=42)
    before = (
        session.world,
        session.character,
        session.combat,
        session.progress,
        session.dice.checkpoint(),
    )
    turn = commit(session)
    assert turn.scene and turn.scene.proposal.facts == (FACT,)
    assert turn.dialogue.target == "guard"
    assert session.narrations[-1].segments[-1].speaker_id == "guard"
    assert (
        session.world,
        session.character,
        session.combat,
        session.progress,
        session.dice.checkpoint(),
    ) == before
    assert not session.memory.events[-1].changes
    slots = SaveSlots(tmp_path)
    slots.save(1, session)
    restored = slots.load(1)
    assert restored.to_dict() == session.to_dict()
    assert restored.submit("бросить кубик").roll.value == 4
    assert FACT.value in str(retrieve(restored, "площадь гул"))


def test_approach_and_question_is_one_complete_social_scene():
    session = Session(seed=42)
    value = proposal(
        focus="villager",
        facts=(),
        text=(
            "Вы подходите к девушке. Жительница придерживает корзину коленом. "
            "«Спасибо, держусь. Только яблоки рассыпались, а мне ещё на рынок успеть»."
        ),
    )
    turn = commit(session, value, "подойду к девушке и спрошу, как у нее дела")
    assert turn.dialogue.act == "question"
    assert turn.dialogue.target == "villager"
    assert session.world.quest == "available"
    assert "другое действие не выполнено" not in turn.text


def test_story_facts_cannot_be_replaced_and_invalid_commit_is_atomic():
    session = Session(seed=42)
    commit(session)
    before = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError, match="установленный факт"):
        commit(session, proposal(facts=(replace(FACT, value="Гул доносится от кузницы."),)))
    assert (session.to_dict(), session.dice.checkpoint()) == before
    commit(session)  # Reusing the same established fact is permitted.


@pytest.mark.parametrize("change", ["stale", "remote", "dead", "hostile", "combat"])
def test_scene_preconditions_are_enforced(change):
    session = Session(seed=42)
    value = proposal()
    revision = 0
    if change == "stale":
        revision = 1
    elif change == "remote":
        value = proposal(focus="merchant", facts=())
    elif change == "dead":
        session.world = replace(session.world, hp=0)
    elif change == "hostile":
        session.submit("поссориться со стражником")
        revision = 1
    else:
        session.submit("атаковать стражника")
        revision = len(session.turns)
    with pytest.raises(ValueError):
        session.submit_scene("привет", value, "test:1", base_turn=revision)


@pytest.mark.parametrize(
    "key,value",
    [("hp", "много"), ("motive", "Получено двадцать золотых"), ("concern", "Рана наносит 5 урона")],
)
def test_facts_cannot_assign_mechanics(key, value):
    with pytest.raises(ValueError):
        StoryFact("guard", key, value)


def test_facts_cannot_modify_an_unseen_subject():
    session = Session(seed=42)
    with pytest.raises(ValueError, match="вне текущей"):
        commit(session, proposal(facts=(StoryFact("merchant", "motive", "Ждёт покупателя."),)))


def test_story_commit_rolls_back_if_narration_fails(monkeypatch):
    session = Session(seed=42)
    before = session.to_dict()

    def fail(*args):
        raise ValueError("note rejected")

    monkeypatch.setattr(Session, "add_narration", fail)
    with pytest.raises(ValueError, match="note rejected"):
        commit(session)
    assert session.to_dict() == before


def test_story_commit_rolls_back_if_memory_fails(monkeypatch):
    session = Session(seed=42)
    before = session.to_dict()

    def fail(*args):
        raise ValueError("event rejected")

    monkeypatch.setattr(WorldMemory, "append", fail)
    with pytest.raises(ValueError):
        commit(session)
    assert session.to_dict() == before


@pytest.mark.parametrize("field", ["location", "base_turn", "text", "focus"])
def test_saved_scene_tampering_is_rejected(field):
    session = Session(seed=42)
    commit(session)
    data = deepcopy(session.to_dict())
    turn = data["turns"][0]
    if field == "text":
        turn["text"] = "Совсем другое событие."
    elif field == "focus":
        turn["scene"]["proposal"]["focus_id"] = "merchant"
    else:
        turn["scene"][field] = "road" if field == "location" else 1
    with pytest.raises(ValueError):
        Session.from_dict(data)


def test_sqlite_contains_full_session_and_can_restore_it(tmp_path):
    session = Session(seed=42)
    commit(session)
    session.submit("бросить кубик")
    path = tmp_path / "campaign.sqlite3"
    export_session(session, path)
    restored = restore_session(path)
    assert restored.to_dict() == session.to_dict()
    assert restored.submit("бросить кубик").roll.value == 1
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        export_session(session, path)
    assert path.read_bytes() == original


def test_retrieval_is_bounded_and_can_find_old_facts():
    session = Session(seed=42)
    commit(session)
    for _ in range(30):
        session.submit("осмотреться")
    index = CampaignIndex(session)
    try:
        context = index.retrieve("гул площадь", budget=1000)
        assert len(json.dumps(context, ensure_ascii=False)) <= 1000
        assert any(item["value"] == FACT.value for item in context["facts"])
        assert len(context["events"]) <= 4
        assert len(context["examples"]) <= 2
        assert index.db.execute("SELECT count(*) FROM events").fetchone()[0] == 31
        assert index.db.execute("SELECT count(*) FROM relationships").fetchone()[0] == 5
        assert index.db.execute("SELECT count(*) FROM inventory").fetchone()[0] == 1
    finally:
        index.close()


def test_sql_queries_treat_input_as_data():
    session = Session(seed=42)
    index = CampaignIndex(session)
    try:
        index.retrieve("'; DROP TABLE facts; -- рассказ")
        assert index.db.execute("SELECT count(*) FROM entities").fetchone()[0] > 0
    finally:
        index.close()


def test_actual_v11_save_preserves_both_rolls_and_future_rng():
    path = Path(__file__).parent / "fixtures" / "save-v11.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    session = Session.from_dict(data["session"], version=11)
    assert len(session.turns[0].inspection.rolls) == 2
    assert session.submit("бросить кубик").roll.value == 12


def test_pure_nash_and_maximin_reference_cases():
    dilemma = (((3, 3), (0, 5)), ((5, 0), (1, 1)))
    result = analyse_game(dilemma)
    assert result["pure_nash"] == ((1, 1),)
    assert result["npc_maximin"] == (1,)
    matching = (((1, -1), (-1, 1)), ((-1, 1), (1, -1)))
    assert analyse_game(matching)["pure_nash"] == ()
    assert peaceful_contact()["version"] == "contact-game-homebrew-1"


@pytest.mark.parametrize("matrix", [[], [[]], [[[1, 2]], []], [[[float("nan"), 0]]]])
def test_invalid_games_are_rejected(matrix):
    with pytest.raises(ValueError):
        analyse_game(matrix)


def test_sqlite_private_facts_not_sent_to_model_and_relations_are_selected():
    session = Session(seed=42)
    session.submit("жительница, ты дура")
    index = CampaignIndex(session)
    try:
        index.db.execute(
            "INSERT INTO facts VALUES (?,?,?,?)",
            ("gate", "hidden", "Тайный ход за амбаром.", "private"),
        )
        result = index.retrieve("тайный ход")
        assert "Тайный ход" not in json.dumps(result, ensure_ascii=False)
        villager = next(n for n in result["npcs"] if n["id"] == "villager")
        assert villager["relationship"]["grievance"] == 1
    finally:
        index.close()


def test_sqlite_ui_import_restores_full_state(window, qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from rpg_vkr.ui.narrator_panel import import_campaign

    session = Session(seed=5)
    commit(session)
    path = tmp_path / "restore.sqlite3"
    export_session(session, path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    import_campaign(window)
    assert window._session.to_dict() == session.to_dict()
    assert not window._dirty


def test_new_window_defaults_to_scene_master(qt_app, tmp_path):
    from rpg_vkr.ui.main_window import MainWindow

    widget = MainWindow(session=Session(seed=42), saves=SaveSlots(tmp_path / "slots"))
    assert widget.director_mode.isChecked()
    assert not hasattr(widget, "manual_chatgpt")
    widget.close()
    widget.deleteLater()
