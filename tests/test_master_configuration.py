"""Editable instructions and saved world preferences; no real inference or billing."""

import hashlib
import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialogButtonBox
from test_local_narrator import local_server, wait_for

from rpg_vkr.application import Session
from rpg_vkr.domain.campaign import WORLD_BRIEF_LIMIT
from rpg_vkr.domain.character import Character
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.instructions import instruction_hash, load_instructions
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.ollama import OllamaClient
from rpg_vkr.narrative.story import story_payload
from rpg_vkr.storage.knowledge import export_session, restore_session
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.creation_dialog import CreationDialog

ROOT = Path(__file__).resolve().parents[1]


def test_editable_instruction_is_loaded_for_each_request_and_core_rules_remain(
    tmp_path, monkeypatch
):
    import rpg_vkr.narrative.instructions as instructions

    default = tmp_path / "default.txt"
    local = tmp_path / "local.txt"
    default.write_text("Пиши ясно, точно и с лёгкой иронией.", encoding="utf-8")
    monkeypatch.setattr(instructions, "DEFAULT_PATH", default)
    monkeypatch.setattr(instructions, "LOCAL_PATH", local)
    frame = build_frame(Session(seed=5))
    before = story_payload(frame, "deepseek/deepseek-v4-pro-0813", "Осмотреться")
    local.write_text("Пиши сдержанно, как рассказчик морских приключений.", encoding="utf-8-sig")
    after = story_payload(frame, "deepseek/deepseek-v4-pro-0813", "Осмотреться")
    assert "лёгкой иронией" in before["messages"][0]["content"]
    assert "морских приключений" in after["messages"][0]["content"]
    assert "лёгкой иронией" not in after["messages"][0]["content"]
    assert (
        "Числовые последствия и механические действия определяет движок"
        in (after["messages"][0]["content"])
    )
    assert "Нападение на нейтрального NPC возможно" in after["messages"][0]["content"]
    assert after["options"]["num_predict"] == 900
    assert instruction_hash(before["messages"][0]["content"]) != instruction_hash(
        after["messages"][0]["content"]
    )


@pytest.mark.parametrize("raw", [b"", b"\x98", b"a\x00b", b"x" * 65537])
def test_invalid_instruction_is_rejected_instead_of_silently_using_another(raw, tmp_path):
    default = tmp_path / "default.txt"
    local = tmp_path / "local.txt"
    default.write_text("Исправная инструкция.", encoding="utf-8")
    local.write_bytes(raw)
    with pytest.raises(ValueError):
        load_instructions(default_path=default, local_path=local)


def test_bad_prompt_stops_before_any_model_request(qt_app, tmp_path, monkeypatch):
    import rpg_vkr.narrative.instructions as instructions

    invalid = tmp_path / "local.txt"
    invalid.write_text("", encoding="utf-8")
    monkeypatch.setattr(instructions, "LOCAL_PATH", invalid)
    client = OllamaClient()
    client.models = ("local-test:1",)
    errors = []
    client.failed.connect(errors.append)
    with local_server() as (url, requests):
        client.base_url = url
        client.develop(
            build_frame(Session(seed=5)), "local-test:1", "Осмотрюсь", memory={}, campaign={}
        )
        assert errors and not client.busy
        assert requests == []


def test_world_brief_is_separate_from_hero_and_survives_json_and_sqlite(tmp_path):
    description = "Мира — дочь лодочника, ищет брата."
    brief = "Морское фэнтези. Редкая магия, интриги гильдий. Без пророчеств."
    session = Session.create_hero(
        Character(name="Мира"), "scout", seed=5, description=description, world_brief=brief
    )
    before = session.world, session.character, session.combat, session.dice.checkpoint()
    payload = story_payload(
        build_frame(session),
        "deepseek/deepseek-v4-pro-0813",
        "Осмотрюсь",
        campaign=campaign_context(session),
    )
    assert brief in payload["messages"][1]["content"]
    assert description in payload["messages"][1]["content"]
    assert brief not in payload["messages"][0]["content"]
    assert session.campaign.world_brief == brief
    assert session.campaign.raw_player_description == description
    assert (session.world, session.character, session.combat, session.dice.checkpoint()) == before
    slots = SaveSlots(tmp_path / "saves")
    slots.save(1, session)
    assert slots.load(1).to_dict() == session.to_dict()
    export_session(session, tmp_path / "world.sqlite3")
    assert restore_session(tmp_path / "world.sqlite3").to_dict() == session.to_dict()


def test_creation_world_field_has_independent_limit_and_does_not_rewrite_biography(qt_app):
    dialog = CreationDialog()
    dialog.description_input.setPlainText("Дочь лодочника.")
    dialog.world_brief_input.setPlainText("Морское фэнтези и политика.")
    session = dialog.create_session()
    assert session.campaign.raw_player_description == "Дочь лодочника."
    assert session.campaign.world_brief == "Морское фэнтези и политика."
    dialog.world_brief_input.setPlainText("М" * (WORLD_BRIEF_LIMIT + 1))
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    with pytest.raises(ValueError):
        dialog.create_session()
    dialog.world_brief_input.clear()
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.close()


def test_world_brief_cannot_be_disguised_as_a_legacy_schema():
    session = Session.create_hero(Character(), "scout", seed=5, world_brief="Морское фэнтези")
    with pytest.raises(ValueError, match="schema 17"):
        Session.from_dict(session.to_dict(), version=16)


def test_real_v16_fixture_preserves_canon_prose_and_rng_without_rewriting_source(tmp_path):
    raw = (ROOT / "tests/fixtures/save-v16.json").read_bytes()
    source = json.loads((ROOT / "tests/fixtures/save-v16.source.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == source["sha256"]
    slots = SaveSlots(tmp_path)
    (tmp_path / "slot-1.json").write_bytes(raw)
    session = slots.load(1)
    original = json.loads(raw)["session"]
    assert session.campaign.world_brief == ""
    assert json.loads(json.dumps(session.campaign.to_dict())) == original["campaign"]
    notes = json.loads(json.dumps([n.to_dict() for n in session.narrations]))
    assert notes == original["narrations"]
    checkpoint = session.dice.checkpoint()
    slots.save(2, session)
    restored = slots.load(2)
    assert restored.to_dict() == session.to_dict()
    assert restored.dice.checkpoint() == checkpoint
    assert restored.dice.roll_d20() == session.dice.roll_d20()
    assert (tmp_path / "slot-1.json").read_bytes() == raw


def test_real_transport_sends_instruction_and_persists_its_hash(qt_app, tmp_path, monkeypatch):
    import rpg_vkr.narrative.instructions as instructions

    local = tmp_path / "local.txt"
    local.write_text("Говори ясно. Используй бытовые детали.", encoding="utf-8")
    monkeypatch.setattr(instructions, "LOCAL_PATH", local)
    with local_server(mode="plain_probe") as (url, requests):
        client = OllamaClient(base_url=url)
        client.models = ("local-test:1",)
        notes, errors = [], []
        client.narration_ready.connect(notes.append)
        client.failed.connect(errors.append)
        client.narrate(build_frame(Session(seed=5)), "local-test:1", plain=True)
        wait_for(qt_app, lambda: notes or errors)
        assert notes, errors
        system = next(body for path, body in requests if path == "/api/chat")["messages"][0][
            "content"
        ]
        assert "бытовые детали" in system
        assert notes[0].instruction_hash == instruction_hash(system)
        assert notes[0].prompt_version == "narrator-prose-12"
