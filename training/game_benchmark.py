"""Authored engine -> existing OllamaClient -> checked prose benchmark, never user saves."""

import argparse
import json
import tempfile
import time
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from random import Random

from rpg_vkr.domain.adventure import build_world
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.receipts import receipt
from rpg_vkr.domain.unified import CLASSES
from rpg_vkr.narrative.local_models import local_models
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.unified_session import UnifiedSession
from training.ollama_probe import FAUN_MODEL, request

CASES = (
    "bow_damage",
    "bow_partial",
    "bow_success",
    "armour_repair",
    "spear",
    "broom",
    "coins",
    "coins_no_magic",
    "glove",
    "road",
    "food",
)


def scenario(case):
    natural = {"bow_damage": 3, "bow_partial": 12, "bow_success": 20}.get(case, 20)
    seed = next(n for n in range(10000) if Random(n).randint(1, 20) == natural)
    class_id = "mage" if case == "coins" else "archer"
    char = Character(**dict(zip(ABILITY_NAMES, CLASSES[class_id][3], strict=True)))
    s = UnifiedSession.create(
        char,
        class_id,
        CLASSES[class_id][4],
        seed=seed,
        catalog_revision=3,
        description="SYNTHETIC_BENCHMARK_NOT_SFT",
    )
    definitions = []
    entities = []
    for id, name, props, condition in (
        (
            "broom",
            "Обычная метла",
            {"portable": True, "affordances": ["rigid", "shaft", "wood"]},
            20,
        ),
        (
            "pole",
            "Ясеневое древко",
            {"portable": True, "affordances": ["shaft", "wood", "rigid"]},
            20,
        ),
        ("glove", "Рукавица", {"portable": True}, 20),
        ("mail", "Сломанный доспех", {"game_template_id": "gear_light_0_0"}, 1),
        ("tools", "Ремонтные инструменты", {"game_template_id": "house_0_0"}, 20),
        ("cloth", "Ткань для ремонта", {"game_template_id": "mat_3_0"}, 20),
    ):
        definitions.append(
            {
                "id": "type_" + id,
                "name": name,
                "kind": "item",
                "categories": ["miscellaneous"],
                "properties": props,
            }
        )
        entities.append(
            {
                "id": id,
                "definition_id": "type_" + id,
                "parent_id": "camp" if id == "glove" else "hero",
                "owner_id": "" if id == "glove" else "hero",
                "state": {"condition": condition},
            }
        )
    for id, name, job in (("resident", "Житель", "resident"), ("captain", "Стражник", "guard")):
        definitions.append(
            {
                "id": "type_" + id,
                "name": name,
                "kind": "actor",
                "categories": ["npcs"],
                "properties": {"hp_max": 10, "class": job},
            }
        )
        entities.append(
            {"id": id, "definition_id": "type_" + id, "parent_id": "camp", "state": {"hp": 10}}
        )
    world = {
        "title": "Испытательный лагерь",
        "opening": "У костра стоят жители; рядом начинается дорога.",
        "private_plot": "Авторский технический сценарий без личных данных.",
        "hooks": ["Проверить последствия"],
        "start": "camp",
        "places": [
            {"id": "camp", "name": "Лагерь", "parent": "", "description": "Тихий лагерь."},
            {
                "id": "road",
                "name": "Дорога к шахте",
                "parent": "camp",
                "description": "Открытая дорога.",
            },
        ],
        "definitions": definitions,
        "entities": entities,
    }
    s.start_world(build_world(world, s, "synthetic-faun-benchmark"))
    if case == "food":
        s.perform_gameplay("wait", {"minutes": 1440}, "benchmark-day")
    return s


def execute_case(case):
    s = scenario(case)
    text = {
        "armour_repair": "Ремонтирую сломанный доспех",
        "spear": "Делаю копьё из ясеневого древка",
        "broom": "Сажусь на метлу и пытаюсь взлететь",
        "coins": "Пытаюсь наколдовать сто золотых монет",
        "coins_no_magic": "Пытаюсь наколдовать сто золотых монет",
        "glove": "Подбираю рукавицу",
        "road": "Иду по дороге к шахте",
        "food": "Предлагаю распределить продовольствие между жителями и гарнизоном",
    }.get(case, "Разбираю свой лук и делаю из него удочку")
    s.submit(text)
    with tempfile.TemporaryDirectory(prefix="dnd-benchmark-") as folder:
        slots = SaveSlots(Path(folder))
        slots.save(1, s)
        loaded = slots.load(1)
        assert loaded.to_dict() == s.to_dict() and loaded.dice.checkpoint() == s.dice.checkpoint()
    return s, text


def narrate(session, text, model, *, client_factory=None):
    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

    from rpg_vkr.narrative.context import build_frame
    from rpg_vkr.narrative.master import campaign_context
    from rpg_vkr.narrative.ollama import OllamaClient

    app = QCoreApplication.instance() or QCoreApplication([])
    client = (client_factory or OllamaClient)(timeout_ms=600000)
    client.story_timeout_ms = 600000
    client.models = (model,)
    client.begin_turn()
    loop = QEventLoop()
    result = {}
    diagnostics = []

    def observed_diagnostic(value):
        # The client redacts prompts/headers/thinking and bounds visible model text.
        diagnostics.append(value[:16000])
        del diagnostics[:-2]

    def accepted(note):
        result.update(status="accepted", text=note.text)
        loop.quit()

    def failed(message):
        result.update(status="rejected_or_unavailable", reason=message)
        loop.quit()

    client.narration_ready.connect(accepted)
    client.failed.connect(failed)
    client.diagnostics_ready.connect(observed_diagnostic)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: failed("benchmark timeout"))
    timer.start(610000)
    import os

    from training.setup_faun import WindowsHost

    memory = WindowsHost().memory_usage if os.name == "nt" else lambda: None
    memory_before = memory()
    started = time.perf_counter()
    client.narrate(
        build_frame(session),
        model,
        player_message=text,
        plain=True,
        campaign=campaign_context(session, query=text),
    )
    if not result:
        loop.exec()
    timer.stop()
    client.cancel()
    result["elapsed_seconds"] = time.perf_counter() - started
    result["events"] = deepcopy(client.events)
    result["response_diagnostics"] = diagnostics
    result["ollama_working_set_before"] = memory_before
    result["ollama_working_set_after"] = memory()
    timings = [e["local_timing"] for e in client.events if "local_timing" in e]
    duration = sum(t.get("eval_duration", 0) for t in timings) / 1e9
    tokens = sum(t.get("eval_count", 0) for t in timings)
    result["tokens_per_second"] = tokens / duration if duration else None
    result["load_seconds"] = sum(t.get("load_duration", 0) for t in timings) / 1e9
    client.deleteLater()
    app.processEvents()
    return result


def run(*, model=FAUN_MODEL, live=False, limit=3, narrator=narrate, requester=request):
    result = {
        "schema": "faun-game-benchmark-v1",
        "source": "SYNTHETIC_ENGINE_SCENARIOS_NOT_SFT",
        "model": model,
        "mode": "live_local" if live else "contracts_without_model",
        "cases": [],
        "human_quality_review": "NOT_PERFORMED",
        "training_steps": 0,
    }
    if live:
        try:
            tags = requester("/api/tags")
        except (OSError, ValueError):
            return result | {"status": "BLOCKED_PROVIDER"}
        installed = next(
            (
                m
                for m in tags.get("models", [])
                if m.get("name", "").casefold() == model.casefold()
                and m["name"] in local_models(tags)
            ),
            None,
        )
        if not installed:
            return result | {"status": "BLOCKED_MODEL"}
        result["installed_digest"] = installed.get("digest")
    for case in CASES[:limit]:
        s, text = execute_case(case)
        before = deepcopy(s.gameplay), s.dice.checkpoint(), asdict(s.world)
        reply = narrator(s, text, model) if live else {"status": "NOT_RUN_CONTRACT_ONLY"}
        assert before == (s.gameplay, s.dice.checkpoint(), asdict(s.world))
        result["cases"].append(
            {
                "id": case,
                "action": text,
                "receipt": receipt(s),
                "save_replay_equal": True,
                "narration_did_not_apply_action_again": True,
                "narration": reply,
            }
        )
    result["accepted_replies"] = sum(
        c["narration"]["status"] == "accepted" for c in result["cases"]
    )
    result["status"] = "CONTRACTS_PASSED_MODEL_NOT_RUN"
    if live:
        result["status"] = (
            "LIVE_COMPLETED_REQUIRES_HUMAN_REVIEW"
            if result["accepted_replies"] == len(result["cases"])
            else "LIVE_DEGRADED_REQUIRES_REVIEW"
        )
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--live", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--model", default=FAUN_MODEL)
    a = p.parse_args()
    result = run(
        model=a.model, live=a.live, limit=len(CASES) if a.all else max(1, min(a.limit, len(CASES)))
    )
    with a.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(
        json.dumps({"status": result["status"], "cases": len(result["cases"]), "training_steps": 0})
    )


if __name__ == "__main__":
    main()
