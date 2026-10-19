"""Grounded prompt/speaker regressions; no trained model or grammar judge is used."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_local_narrator import local_server

from rpg_vkr.application import Session
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.dialogue import last_interlocutor
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.story import repair_payload, story_context, story_payload, story_proposal
from rpg_vkr.storage.knowledge import CampaignIndex, export_session, restore_session, retrieve
from rpg_vkr.storage.slots import SaveSlots

ROOT = Path(__file__).resolve().parents[1]


def test_new_user_language_sample_is_not_accepted_as_a_turn():
    source = json.loads(
        (ROOT / "docs/validation/windows-qwen-language-2026-10-19.json").read_text(encoding="utf-8")
    )
    session = Session(seed=42)
    before = session.to_dict()
    with pytest.raises(ValueError) as caught:
        story_proposal(
            {"message": {"role": "assistant", "content": source["response"]}},
            build_frame(session),
            source["input"],
        )
    assert "реплику за игрока" in str(caught.value)
    assert "подход героя описан несколько раз" in str(caught.value)
    assert session.to_dict() == before


def test_real_v14_scene_is_archived_without_recycling_its_corrupt_speech(tmp_path):
    raw = (ROOT / "tests/fixtures/save-v14.json").read_bytes()
    slots = SaveSlots(tmp_path / "saves")
    slots.directory.mkdir()
    (slots.directory / "slot-1.json").write_bytes(raw)
    session = slots.load(1)
    assert session.turns[-1].scene.version == "scene-director-3"
    assert session.narrations[-1].prompt_version == "narrator-prose-9"
    assert "…Нет, я не видел" in session.turns[-1].text
    text = "как у нее дела?"
    context = story_context(
        build_frame(session),
        "qwen2.5:7b",
        text,
        memory=retrieve(session, text),
        campaign=campaign_context(session, last_interlocutor(session)),
        history=[
            {"source": t.scene.version, "result": t.text, "player": t.action} for t in session.turns
        ],
    )
    payload = story_payload(build_frame(session), "qwen2.5:7b", text, context=context)
    assert "…Нет, я не видел" not in json.dumps(payload, ensure_ascii=False)
    assert last_interlocutor(session) == "villager"
    index = CampaignIndex(session)
    try:
        assert (
            "…Нет, я не видел"
            in index.db.execute("SELECT result FROM events ORDER BY turn DESC LIMIT 1").fetchone()[
                0
            ]
        )
    finally:
        index.close()
    path = tmp_path / "campaign.sqlite3"
    export_session(session, path)
    restored = restore_session(path)
    assert restored.to_dict() == session.to_dict()
    assert restored.submit("бросить кубик").roll.value == 4
    assert (slots.directory / "slot-1.json").read_bytes() == raw
    slots.save(2, session)
    assert slots.load(2).to_dict() == session.to_dict()


def test_writer_gets_readable_russian_tasks_and_a_single_speaker():
    session = Session(seed=42)
    text = "подойду к девушке и спрошу, нужна ли ей помощь и как ее зовут"
    payload = story_payload(
        build_frame(session),
        "qwen2.5:7b",
        text,
        memory=retrieve(session, text),
        campaign=campaign_context(session),
    )
    prompt = payload["messages"][1]["content"]
    assert not prompt.startswith("{")
    assert "Игрок написал: " + json.dumps(text, ensure_ascii=False) in prompt
    assert "В этом ходе говорит только: Жительница" in prompt
    assert "Занятие: собирает рассыпавшиеся яблоки" in prompt
    assert "Нужно ответить:" in prompt
    assert "turn_brief" not in prompt and "public_name" not in prompt
    assert "не сочиняй за него ответы" in payload["messages"][0]["content"]
    assert payload["options"]["repeat_penalty"] == 1.0
    assert "think" not in payload and "/no_think" not in prompt


def test_small_model_receives_a_shorter_turn_not_a_multi_scene_story():
    frame = build_frame(Session(seed=42))
    small = story_payload(frame, "qwen3:1.7b", "подойду к девушке")
    standard = story_payload(frame, "qwen2.5:7b", "подойду к девушке")
    assert small["options"]["num_predict"] == 320 < standard["options"]["num_predict"]
    assert "1–3 коротких предложения" in small["messages"][1]["content"]
    assert small["think"] is False and small["messages"][1]["content"].endswith("/no_think")
    assert "3–6" not in small["messages"][0]["content"]
    assert repair_payload(small, "ошибка")["options"]["num_predict"] == 450


@pytest.mark.parametrize(
    "reply",
    [
        "Вы: Нет, я ничего не видел. Женщина ждёт следующего вопроса.",
        "«Добрый день», — говорит женщина.\n…Нет, я пока не спрашивал.",
    ],
)
def test_unassigned_player_replies_are_rejected_without_banning_npc_first_person(reply):
    frame = build_frame(Session(seed=42))
    with pytest.raises(ValueError, match="реплику за игрока"):
        story_proposal(
            {"message": {"role": "assistant", "content": reply}}, frame, "подойду к девушке"
        )
    good = "Вы подходите к женщине. «Я собираю яблоки. Вы хотели поговорить?»"
    assert (
        story_proposal(
            {"message": {"role": "assistant", "content": good}}, frame, "подойду к девушке"
        ).focus_id
        == "villager"
    )


@pytest.mark.parametrize("reference_installed", [True, False])
def test_cli_comparison_uses_the_same_initial_world_without_touching_user_saves(
    tmp_path, monkeypatch, reference_installed
):
    import test_local_narrator

    monkeypatch.setattr(
        test_local_narrator,
        "LOCAL_MODELS",
        {
            "models": [
                {"name": "qwen2.5:7b", "size": 12345, "digest": "synthetic-seven"},
                {"name": "qwen3:1.7b", "size": 2345, "digest": "synthetic-small"},
            ]
        },
    )
    if not reference_installed:
        monkeypatch.setattr(
            test_local_narrator,
            "LOCAL_MODELS",
            {"models": [{"name": "qwen2.5:7b", "size": 12345, "digest": "synthetic-seven"}]},
        )
    with local_server(mode="plain_probe") as (url, requests):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/check_narrator.py"),
                "--model",
                "qwen2.5:7b",
                "--compare-with",
                "qwen3:1.7b",
                "--base-url",
                url,
                "--report-dir",
                str(tmp_path / "reports"),
            ],
            cwd=ROOT,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(next((tmp_path / "reports").glob("*.json")).read_text(encoding="utf-8"))
    assert report["literary_review"] == "pending"
    readable = next((tmp_path / "reports").glob("*.txt")).read_text(encoding="utf-8")
    assert "Модель: qwen2.5:7b" in readable
    if reference_installed:
        assert "Модель: qwen3:1.7b" in readable
    else:
        assert report["comparison_skipped"] == ["qwen3:1.7b"]
        assert "Сравнение пропущено" in readable
        assert len(report["comparison"]) == 1
        assert report["comparison"][0]["protocol_passed"]
        return
    assert "ожидает оценки человеком" in readable
    assert "НЕ ОЦЕНЕНО" in completed.stdout
    assert len(report["comparison"]) == 2
    first, second = report["comparison"]
    assert first["protocol_passed"] and second["protocol_passed"]
    assert [c["input"] for c in first["cases"]] == [c["input"] for c in second["cases"]]
    assert first["cases"][3]["brief"]["public_name"] == second["cases"][3]["brief"]["public_name"]
    assert all(run["literary_review"] == "pending" for run in report["comparison"])
    calls = [body for path, body in requests if path == "/api/chat"]
    assert len(calls) == 8
    unloaded = [body for path, body in requests if path == "/api/generate"]
    assert [body["model"] for body in unloaded] == ["qwen2.5:7b", "qwen3:1.7b"]
    assert all(body["keep_alive"] == 0 for body in unloaded)
    assert "think" not in calls[0] and calls[4]["think"] is False
    assert not (tmp_path / "saves").exists()
