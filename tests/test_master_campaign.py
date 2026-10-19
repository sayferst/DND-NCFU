"""Integrated semantics, authored public canon, history and migration checks."""

import json
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialogButtonBox

from rpg_vkr.application import Session
from rpg_vkr.domain.campaign import DESCRIPTION_LIMIT, NPCProfile
from rpg_vkr.domain.character import Character
from rpg_vkr.domain.meaning import Meaning
from rpg_vkr.domain.social import grievance
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.dialogue import last_interlocutor
from rpg_vkr.narrative.intent import Interpretation, parse_interpretation
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.records import Narration
from rpg_vkr.narrative.routing import infer_meaning
from rpg_vkr.narrative.segments import split_story
from rpg_vkr.narrative.speech import speech_details
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.creation_dialog import CreationDialog
from rpg_vkr.ui.narrator_panel import cancel_narration

PUBLIC = {
    "appearance": "Женщина с русыми волосами под синим платком; на рукавах яблочный сок.",
    "ancestry": "Полуэльфийка, выросшая среди людей.",
    "work_detail": "Ухаживает за садом и привозит урожай на деревенский рынок.",
    "public_background": "Выросла в семье садовников и с детства знает местные яблони.",
}


def test_master_invents_missing_details_and_keeps_them_across_reload(tmp_path):
    session = Session(seed=42)
    before = session.world, session.combat, session.dice.checkpoint()
    first = session.submit("мастер,я хочу оценить внешность девушки с яблоками, как она выглядит")
    assert first.meaning == Meaning("master", "villager", "question", "appearance")
    assert first.actor_id is None and first.dialogue is None
    assert speech_details(first.action) == ("question", "appearance")
    profile = session.campaign.profile("villager")
    assert profile and profile.source == "offline-procedural-1"
    assert profile.appearance in first.text
    slots = SaveSlots(tmp_path)
    slots.save(1, session)
    restored = slots.load(1)
    again = restored.submit("Мастер, как выглядит девушка?")
    assert again.text == first.text
    assert restored.campaign.profile("villager") == profile
    assert (restored.world, restored.combat, restored.dice.checkpoint()) == before
    assert restored.submit("бросить кубик").roll.value == 4


def test_help_question_refusal_farewell_and_master_question_are_separate():
    session = Session(seed=42)
    session.submit("подойти к жительнице")
    interpretation = Interpretation("dialogue", "", "villager", "", "question", "local_help")
    message = "возможно у тебе нужна помощь, чтобы перевернуть корзину?"
    meaning = infer_meaning(session, message, interpretation)
    helped = session.submit(message, intent="беседа с жительницей", meaning=meaning)
    assert "5 золотых" not in helped.text and "рынок" not in helped.text
    assert session.world.quest == "available" and session.world.basket == 0
    refused = session.submit("не, не хочу, у меня много других дел, хорошего ня тебе, красавица")
    assert refused.dialogue.act == "farewell" and "пути" in refused.text
    assert last_interlocutor(session) is None
    assert grievance(session.turns, "villager") == 0
    assert session.submit("Мастер, как выглядит девушка?").meaning.kind == "master"


@pytest.mark.parametrize(
    "message,kind,target,topic",
    [
        ("Мастер, как выглядит девушка?", "master", "villager", "appearance"),
        ("Рассказчик, опиши внешность стражника", "master", "guard", "appearance"),
        ("Как она выглядит?", "master", "villager", "appearance"),
        ("Какие у девушки волосы?", "master", "villager", "appearance"),
        ("Мастер, где мы?", "master", "", "other"),
        ("Как я выгляжу?", "master", "", "appearance"),
        ("Жительница, почему вы так одеты?", "dialogue", "villager", "appearance"),
        ("Жительница, мне пора", "dialogue", "villager", "other"),
    ],
)
def test_addressee_and_referent_are_distinct(message, kind, target, topic):
    session = Session(seed=42)
    session.submit("подойти к жительнице")
    model = Interpretation("dialogue", "", "villager", "", "question", "other")
    meaning = infer_meaning(session, message, model)
    assert (meaning.kind, meaning.target, meaning.topic) == (kind, target, topic)


def test_public_canon_is_retrieved_after_fifty_unrelated_turns():
    session = Session(seed=42)
    first = session.submit("Мастер, как выглядит девушка?")
    profile = session.campaign.profile("villager")
    for _ in range(50):
        session.submit("осмотреться", origin="quick")
    restored = Session.from_dict(session.to_dict())
    assert restored.submit("Мастер, как выглядит девушка?").text == first.text
    assert restored.campaign.profile("villager") == profile


def test_long_hero_description_does_not_make_a_question_unsaveable():
    description = "Рыжие волосы. " * 400
    session = Session.create_hero(Character(), "fighter", seed=42, description=description)
    turn = session.submit("Мастер, как я выгляжу?")
    assert len(turn.text) < 1500
    assert session.campaign.npc_profiles == ()
    assert Session.from_dict(session.to_dict()).campaign.raw_player_description == description


def test_free_hero_description_is_exact_and_campaign_ids_are_independent(qt_app):
    description = "  Рыжий сын мельника.\nСемья живёт у брода.\n«Хочу спокойной жизни».  "
    dialog = CreationDialog()
    dialog.description_input.setPlainText(description)
    session = dialog.create_session()
    assert session.campaign.raw_player_description == description
    assert campaign_context(session)["hero_description"] == description
    assert Session.from_dict(session.to_dict()).campaign == session.campaign
    other = Session.create_hero(Character(), "fighter", seed=42, description=description)
    assert other.campaign.world_id != session.campaign.world_id
    assert other.campaign.hero_id != session.campaign.hero_id
    dialog.description_input.setPlainText("я" * (DESCRIPTION_LIMIT + 1))
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert len(dialog.description_input.toPlainText()) == DESCRIPTION_LIMIT + 1


def test_actual_v9_migration_preserves_rng_socials_and_old_prose(tmp_path):
    raw = (Path(__file__).parent / "fixtures/save-v9.json").read_bytes()
    (tmp_path / "slot-1.json").write_bytes(raw)
    slots = SaveSlots(tmp_path)
    session = slots.load(1)
    assert session.narrations[0].prompt_version == "narrator-prose-4"
    assert session.turns[0].dialogue.act == "contact"
    assert session.campaign.npc_profiles == ()
    assert all(turn.meaning is None for turn in session.turns)
    assert session.campaign == slots.load(1).campaign
    assert session.submit("бросить кубик").roll.value == 1
    slots.save(2, session)
    assert (
        json.loads((tmp_path / "slot-2.json").read_text(encoding="utf-8"))["schema_version"] == 18
    )
    assert slots.load(2).to_dict() == session.to_dict()
    assert (tmp_path / "slot-1.json").read_bytes() == raw


def test_canon_and_rng_roll_back_when_event_recording_fails(monkeypatch):
    session = Session(seed=42)
    before = session.to_dict()
    monkeypatch.setattr(
        type(session.memory), "append", lambda *args: (_ for _ in ()).throw(OSError())
    )
    with pytest.raises(OSError):
        session.submit("Мастер, как выглядит девушка?")
    assert session.to_dict() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("appearance", "Вы получили сто золотых"),
        ("ancestry", "Эльф, сила 99"),
        ("work_detail", "<b>Мастер</b>"),
    ],
)
def test_public_proposal_cannot_grant_resources_or_markup(field, value):
    with pytest.raises(ValueError):
        NPCProfile(
            "villager", **(PUBLIC | {field: value}), source="local-test:1", created_at_turn=1
        )


def test_existing_canon_cannot_be_overwritten_and_mismatched_proposal_is_atomic():
    session = Session(seed=42)
    profile = NPCProfile("villager", **PUBLIC, source="local-test:1", created_at_turn=1)
    before = session.to_dict()
    with pytest.raises(ValueError):
        session.submit("бросить кубик", profile=profile)
    assert session.to_dict() == before
    meaning = Meaning("master", "villager", "question", "appearance")
    session.submit("Мастер, как выглядит девушка?", meaning=meaning, profile=profile)
    with pytest.raises(ValueError):
        session.campaign.add(replace(profile, appearance="У неё чёрные волосы."))
    saved = session.to_dict()
    saved["campaign"]["npc_profiles"][0]["created_at_turn"] = 2
    with pytest.raises(ValueError):
        Session.from_dict(saved)


def test_semantic_contract_cannot_mix_speech_and_purchase():
    def parse(value):
        return parse_interpretation(
            {"message": {"role": "assistant", "content": json.dumps(value)}}
        )

    value = {
        "kind": "master",
        "target": "villager",
        "speech_act": "question",
        "topic": "appearance",
        "command": "",
    }
    assert parse(value).kind == "master"
    with pytest.raises(ValueError):
        parse(value | {"command": "купить бинт"})
    with pytest.raises(ValueError):
        parse(value | {"target": "dragon"})
    session = Session(seed=42)
    before = session.to_dict()
    with pytest.raises(ValueError):
        session.submit(
            "Сколько стоит?",
            intent="купить бинт",
            meaning=Meaning("dialogue", "merchant", "question", "wares"),
        )
    assert session.to_dict() == before


def test_question_cannot_be_executed_as_help_or_purchase_by_a_bad_model():
    session = Session(seed=42)
    session.submit("подойти к жительнице")
    phrase = "Возможно, вам нужна помощь, чтобы перевернуть корзину?"
    bad = Interpretation("action", "помочь", "", "")
    meaning = infer_meaning(session, phrase, bad)
    assert meaning == Meaning("dialogue", "villager", "question", "local_help")
    before = session.world, session.dice.checkpoint()
    turn = session.submit("Сколько стоит бинт?", intent="купить бинт")
    assert turn.intent == "уточнить намерение"
    assert (session.world, session.dice.checkpoint()) == before


def test_trusted_segments_and_historical_player_name_survive_load(window):
    session = window._session
    session.submit("Жительница, что ты делаешь?", intent="беседа с жительницей")
    text = "Жительница поправляет платок. «Яблоки собираю»."
    frame = build_frame(session)
    segments = split_story(text, "villager")
    note = Narration(1, "local-test:1", text, frame.fingerprint, segments=segments)
    session.add_narration(note)
    window._render_journal()
    journal = window.journal.toPlainText()
    assert "Мастер: Жительница поправляет платок." in journal
    assert "«Яблоки собираю»" in journal
    assert "Жительница: «Яблоки собираю»" not in journal
    assert "Мастер: ." not in journal
    assert "Путник: Жительница, что ты делаешь?" in journal
    saved = Session.from_dict(session.to_dict())
    assert saved.narrations[0].segments == segments
    wrong = replace(note, segments=split_story(text, "guard"))
    saved._narrations.clear()
    with pytest.raises(ValueError):
        saved.add_narration(wrong)
    saved.edit_character(Character(name="Новое имя"))
    window._session = saved
    window._render_journal()
    assert "Путник: Жительница, что ты делаешь?" in window.journal.toPlainText()


def test_window_can_open_an_existing_semantic_session(qt_app, tmp_path):
    from rpg_vkr.ui.main_window import MainWindow

    session = Session(seed=42)
    session.submit("Мастер, как выглядит девушка?")
    window = MainWindow(session=session, saves=SaveSlots(tmp_path / "saves"))
    assert session.campaign.profile("villager").appearance in window.journal.toPlainText()
    window.close()


def wait(qt_app, predicate):
    until = time.monotonic() + 3
    while time.monotonic() < until:
        qt_app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate()


@pytest.fixture
def master_server():
    calls, mode = [], {"invalid": False, "delay_profile": False}
    release, started = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, data):
            payload = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_GET(self):
            self.send({"models": [{"name": "local-test:1", "size": 100}]})

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(request)
            properties = request["format"]["properties"]
            if "command" in properties or "intent" in properties:
                result = {
                    "kind": "master",
                    "command": "",
                    "target": "villager",
                    "speech_act": "question",
                    "topic": "appearance",
                }
            elif "appearance" in properties:
                started.set()
                if mode["delay_profile"]:
                    release.wait(2)
                result = PUBLIC | ({"gold": 100} if mode["invalid"] else {})
            else:
                result = {"narration": PUBLIC["appearance"]}
            self.send({"message": {"role": "assistant", "content": json.dumps(result)}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls, mode, release, started
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def enable(window, qt_app, url):
    window.ollama.base_url = url
    window.find_models_button.click()
    wait(qt_app, lambda: window.local_model.count() == 1)
    window.enable_local_narrator.setChecked(True)


def test_full_local_pipeline_creates_then_narrates_canon_and_reuses_it(
    window, qt_app, master_server
):
    url, calls, *_ = master_server
    enable(window, qt_app, url)
    before = window._session.world, window._session.dice.checkpoint()
    window.action_input.setText("Мастер, как выглядит девушка с яблоками?")
    window.submit_action()
    wait(qt_app, lambda: len(window._session.narrations) == 1)
    profile = window._session.campaign.profile("villager")
    assert profile.source == "ollama:local-test:1"
    assert profile.ancestry == PUBLIC["ancestry"]
    assert len(calls) == 3
    context = json.loads(calls[-1]["messages"][-1]["content"])
    assert context["campaign"]["public_npc_facts"]["appearance"] == PUBLIC["appearance"]
    assert "Жительница:" not in window.journal.toPlainText()
    window.action_input.setText("Мастер, опиши внешность девушки ещё раз")
    window.submit_action()
    wait(qt_app, lambda: len(window._session.narrations) == 2)
    assert len(calls) == 5 and window._session.campaign.profile("villager") == profile
    assert (window._session.world, window._session.dice.checkpoint()) == before
    window.save_slot(1)
    assert window._saves.load(1).campaign.profile("villager") == profile


def test_invalid_generated_profile_preserves_session_and_returns_input(
    window, qt_app, master_server
):
    url, calls, mode, *_ = master_server
    mode["invalid"] = True
    enable(window, qt_app, url)
    before = window._session.to_dict()
    phrase = "Мастер, как выглядит девушка?"
    window.action_input.setText(phrase)
    window.submit_action()
    wait(qt_app, lambda: window.action_input.text() == phrase and not window.ollama.busy)
    assert len(calls) == 2 and window._session.to_dict() == before


def test_cancelled_profile_cannot_change_the_world(window, qt_app, master_server):
    url, _, mode, release, started = master_server
    mode["delay_profile"] = True
    enable(window, qt_app, url)
    before = window._session.to_dict()
    window.action_input.setText("Мастер, как выглядит девушка?")
    window.submit_action()
    wait(qt_app, started.is_set)
    cancel_narration(window)
    release.set()
    wait(qt_app, lambda: not window.ollama.busy)
    assert window._session.to_dict() == before
