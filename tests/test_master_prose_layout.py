"""Offline protocol/rendering checks, not a measurement of model writing quality."""

import json

import pytest

from rpg_vkr.application import Session
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.instructions import DEFAULT_PATH, load_instructions
from rpg_vkr.narrative.story import story_payload, story_proposal, story_text
from rpg_vkr.narrative.story_prompt import writing_profile
from rpg_vkr.ui.role_journal import MessageRole, RoleJournal


def test_shipped_prompt_is_used_and_fits_loader_limits(tmp_path):
    import rpg_vkr.narrative.instructions as instructions

    # Explicitly bypass a developer's optional private override for this check.
    text = load_instructions(default_path=DEFAULT_PATH, local_path=tmp_path / "absent.txt")
    assert len(text) <= instructions.MAX_CHARACTERS
    assert len(text.encode("utf-8")) <= instructions.MAX_BYTES
    assert text.strip()


def test_paragraphs_and_dash_speech_survive_validation_save_and_journal(qt_app, tmp_path):
    from rpg_vkr.storage.slots import SaveSlots

    session = Session(seed=42)
    frame = build_frame(session)
    action = "спросить у жительницы, как дела"
    text = (
        "Женщина отодвигает корзину от дороги.\n\n"
        "— Дела так себе: яблоки рассыпались.\n\n"
        "Она поправляет ручку корзины."
    )
    before = session.world, session.dice.checkpoint()
    proposal = story_proposal({"message": {"role": "assistant", "content": text}}, frame, action)
    session.submit_scene(action, proposal, "test-layout", base_turn=0)
    slots = SaveSlots(tmp_path)
    slots.save(1, session)
    restored = slots.load(1)
    assert restored.turns[-1].text == text
    assert (restored.world, restored.dice.checkpoint()) == before
    journal = RoleJournal()
    journal.append_master_story(restored.turns[-1].text, actor_id="villager")
    assert journal.toPlainText() == "Мастер: " + text
    block = journal.document().findBlockByNumber(2)
    assert block.text() == "— Дела так себе: яблоки рассыпались."
    assert isinstance(block.userData(), MessageRole)
    assert block.userData().actor_id == "villager"
    assert block.userData().speech_only
    journal.deleteLater()


def test_json_compatible_prose_preserves_linebreaks_without_executing_actions():
    text = "Речной город | Мастерская\n\nПереплётчица кивает.\n\n— Сначала осмотрю книгу."
    reply = json.dumps({"narration": text}, ensure_ascii=False)
    assert story_text({"message": {"role": "assistant", "content": reply}}) == text


def test_story_request_keeps_world_wishes_separate_from_system_instructions():
    from rpg_vkr.narrative.master import campaign_context

    session = Session(seed=42)
    campaign = campaign_context(session)
    campaign["world_brief"] = "Морское фэнтези; без пророчеств."
    payload = story_payload(build_frame(session), "deepseek/test", "осмотреться", campaign=campaign)
    assert campaign["world_brief"] in payload["messages"][1]["content"]
    assert campaign["world_brief"] not in payload["messages"][0]["content"]


@pytest.mark.parametrize(
    "text",
    ["Кратко опиши подробности", "Не надо подробно, я ухожу", "Без подробностей о прошлом"],
)
def test_concise_request_does_not_select_large_generation_budget(text):
    model = "~deepseek/deepseek-v4-flash-latest"
    assert writing_profile(model, text)["num_predict"] == writing_profile(model)["num_predict"]
    assert (
        writing_profile(model, text)["num_predict"]
        < writing_profile(model, "подробнее")["num_predict"]
    )


def test_deepseek_alias_uses_same_writing_budget_as_concrete_model():
    assert writing_profile("~deepseek/deepseek-v4-flash-latest") == writing_profile(
        "deepseek/deepseek-v4-flash"
    )
