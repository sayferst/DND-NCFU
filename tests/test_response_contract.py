"""Independent before/after corpus plus real persistence and generic dialogue checks."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from response_cases import MODEL, context_for, new_session, prepare, response

from rpg_vkr.application import Session
from rpg_vkr.domain.receipts import receipt
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.dialogue import last_interlocutor
from rpg_vkr.narrative.story import story_proposal, story_text
from rpg_vkr.narrative.story_quality import check_story_quality
from rpg_vkr.storage.campaigns import CampaignRepository
from rpg_vkr.storage.slots import SaveSlots

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/response-cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_independent_response_corpus(case):
    session = prepare(case)
    before = deepcopy(session.to_dict()), session.dice.checkpoint()
    context = context_for(session, case["message"], case["confirmed"])

    def validate():
        if case["confirmed"]:
            text = story_text(response(case["text"]), confirmed=True)
            check_story_quality(
                text,
                build_frame(session),
                case["message"],
                brief=context["turn_brief"],
                campaign=context,
            )
        else:
            story_proposal(
                response(case["text"]), build_frame(session), case["message"], context=context
            )

    if case["valid"]:
        validate()
    else:
        with pytest.raises(ValueError):
            validate()
    assert (session.to_dict(), session.dice.checkpoint()) == before


def test_new_npc_identity_survives_questions_slots_database_and_restart(tmp_path):
    session = new_session()
    for message, answer in [
        ("Веста, здравствуйте.", "Веста кивает. «Здравствуйте, путник»."),
        ("Как тебя зовут?", "«Я Веста», — отвечает картограф."),
    ]:
        value = story_proposal(
            response(answer), build_frame(session), message, context=context_for(session, message)
        )
        assert value.focus_id == "vesta"
        session.submit_scene(message, value, MODEL, base_turn=len(session.turns))
        assert last_interlocutor(session) == "vesta"
    slots = SaveSlots(tmp_path / "saves")
    slots.save(1, session)
    loaded = slots.load(1)
    assert loaded.to_dict() == session.to_dict()
    db = CampaignRepository(tmp_path / "campaigns.sqlite3")
    db.sync(loaded)
    assert last_interlocutor(db.load(db.identity(loaded))) == "vesta"


def test_long_scene_and_short_npc_reply_persist_without_truncation(tmp_path):
    session = new_session()
    long = next(c["text"] for c in CASES if c["id"] == "long_scene")
    for message, answer in [("Мастер, опиши погоду подробно", long), ("Веста, можно?", "«Да».")]:
        value = story_proposal(
            response(answer), build_frame(session), message, context=context_for(session, message)
        )
        session.submit_scene(message, value, MODEL, base_turn=len(session.turns))
    slots = SaveSlots(tmp_path)
    slots.save(1, session)
    loaded = slots.load(1)
    assert loaded.narrations[0].text == long
    assert loaded.narrations[1].text == "«Да»."


def test_typed_partial_receipt_does_not_consume_rng_and_preserves_prefix():
    session = prepare(next(c for c in CASES if c["id"] == "partial_failure_prefix"))
    rng = session.dice.checkpoint()
    value = receipt(session)
    assert [s["status"] for s in value["steps"]] == ["completed", "failed"]
    assert value["place_id"] == "landing"
    assert receipt(session) == value and session.dice.checkpoint() == rng
    assert receipt(Session.from_dict(session.to_dict())) == value


def test_original_v21_fixture_migrates_without_changing_bytes_or_world(tmp_path):
    path = ROOT / "tests/fixtures/save-v21.json"
    raw = path.read_bytes()
    source = json.loads(path.with_suffix(".source.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == source["sha256"]
    saved = json.loads(raw)
    session = Session.from_dict(saved["session"], version=21)
    slots = SaveSlots(tmp_path)
    slots.save(1, session)
    assert slots.load(1).to_dict() == session.to_dict()
    assert path.read_bytes() == raw
