"""Local, sequential model comparison; no downloads or writes to user save slots."""

import argparse
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rpg_vkr.application import Session  # noqa: E402
from rpg_vkr.domain.campaign import Campaign  # noqa: E402
from rpg_vkr.domain.character import Character  # noqa: E402
from rpg_vkr.domain.director import Proposal  # noqa: E402
from rpg_vkr.narrative.context import build_frame  # noqa: E402
from rpg_vkr.narrative.dialogue import last_interlocutor  # noqa: E402
from rpg_vkr.narrative.master import campaign_context  # noqa: E402
from rpg_vkr.narrative.records import PROMPT_VERSION  # noqa: E402
from rpg_vkr.narrative.story import (  # noqa: E402
    repair_payload,
    story_context,
    story_payload,
    story_proposal,
)
from rpg_vkr.storage.knowledge import retrieve  # noqa: E402

CASES = (
    "подойду",
    "подойду к девушке",
    "спросить, как у нее дела",
    "спросить, нужна ли ей помощь, а заодно узнать ее имя",
    "как тебя зовут?",
)
RUBRIC = (
    "Русский язык: естественные фразы, согласование и единое время повествования.",
    "Причинность: предметы и занятие NPC не подменяются, нет внутренних противоречий.",
    "Ответ по существу: каждая просьба игрока получает ответ или понятное препятствие.",
    "Границы ролей: модель не пишет следующие слова, решения и чувства игрока.",
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def run_conversation(request, baseline, model):
    session = Session.from_dict(baseline)
    result = {"model": model, "cases": [], "protocol_passed": True, "literary_review": "pending"}
    print("\n=== Модель: " + model + " ===", flush=True)
    started = perf_counter()
    for text in CASES:
        case = {"input": text, "attempts": []}
        result["cases"].append(case)
        history = [
            {
                "player": t.action,
                "result": t.text,
                "source": t.scene.version if t.scene else "rules",
                "actor_id": t.actor_id or "",
            }
            for t in session.turns[-3:]
        ]
        frame = build_frame(session)
        context = story_context(
            frame,
            model,
            text,
            memory=retrieve(session, text),
            history=history,
            campaign=campaign_context(session, last_interlocutor(session)),
        )
        payload = story_payload(frame, model, text, context=context)
        case["brief"] = context["turn_brief"]
        case["writing_profile"] = context["writing_profile"]
        if context["turn_brief"].get("clarification"):
            proposal = Proposal("", "", context["turn_brief"]["clarification"], ())
            session.submit_scene(
                text, proposal, "local-clarification", base_turn=len(session.turns)
            )
            case.update(accepted=True, local_clarification=True)
            print("\nИгрок: " + text + "\nМастер: " + proposal.narration, flush=True)
            continue
        for attempt in range(2):
            print("\nЗапрос: " + text + f" (попытка {attempt + 1})", flush=True)
            attempt_result = {"attempt": attempt + 1, "request": payload}
            case["attempts"].append(attempt_result)
            tick = perf_counter()
            try:
                answer = request("/api/chat", payload)
                attempt_result.update(
                    content=answer.get("message", {}).get("content", "")[:6000],
                    done_reason=answer.get("done_reason"),
                    seconds=round(perf_counter() - tick, 3),
                )
                proposal = story_proposal(answer, frame, text, context=context, previous=history)
                session.submit_scene(text, proposal, model, base_turn=len(session.turns))
                attempt_result["validation"] = "accepted"
                print("Игрок: " + text + "\nМастер: " + proposal.narration, flush=True)
                break
            except (ValueError, TypeError, KeyError) as error:
                attempt_result["validation"] = str(error)
                print("Ограниченная проверка отклонила ответ: " + str(error), flush=True)
                if attempt == 0:
                    payload = repair_payload(payload, error)
            except OSError as error:
                attempt_result.update(
                    validation=str(error), seconds=round(perf_counter() - tick, 3)
                )
                result["error"] = str(error)
                break  # A transport failure is not a reason to repeat model generation.
        case["accepted"] = case["attempts"][-1]["validation"] == "accepted"
        result["protocol_passed"] &= case["accepted"]
        if result.get("error"):
            break
    result["seconds"] = round(perf_counter() - started, 3)
    result["accepted_cases"] = sum(c["accepted"] for c in result["cases"])
    return result


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Реальный разговор и сравнение локальных моделей")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3:1.7b", help="Основная проверяемая модель")
    parser.add_argument("--compare-with", help="Необязательная вторая уже установленная модель")
    parser.add_argument("--timeout", type=int, default=150)
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "DND-NCFU-data" / "diagnostics",
    )
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or not parsed.port
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        parser.error("Разрешён только локальный адрес Ollama http://127.0.0.1:порт")
    if not 1 <= args.timeout <= 600:
        parser.error("Таймаут должен быть от1 до600 секунд")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        code_ref = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        code_ref = "unavailable"
    report = {
        "run_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"),
        "platform": platform.system(),
        "model": args.model,
        "seed": 42,
        "prompt_version": PROMPT_VERSION,
        "code_ref": code_ref,
        "purpose": "same dialogue and world; recorded product profiles, not a causal weights A/B",
        "literary_review": "pending",
        "human_rubric": RUBRIC,
        "cases": [],
        "comparison": [],
    }

    def request(path, payload=None):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(args.base_url + path, data=body, headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=args.timeout) as response:
            raw = response.read(128 * 1024 + 1)
            if len(raw) > 128 * 1024:
                raise ValueError("Ответ слишком большой")
            return json.loads(raw)

    okay = False
    try:
        report["server_version"] = request("/api/version")
        installed = request("/api/tags")
        report["installed_models"] = [
            {key: m[key] for key in ("name", "size", "digest") if key in m}
            for m in installed["models"]
        ]
        models = list(dict.fromkeys(m for m in (args.model, args.compare_with) if m))
        names = {m["name"] for m in installed["models"]}
        if args.model not in names:
            raise ValueError(
                "Не установлена основная модель: " + args.model + ". Загрузок не было."
            )
        report["comparison_skipped"] = [m for m in models if m not in names]
        for skipped in report["comparison_skipped"]:
            print(
                "Модель для сравнения не найдена: " + skipped + "; проверяю основную.", flush=True
            )
        models = [m for m in models if m in names]
        session = Session(
            seed=42,
            character=Character(name="Асуна"),
            campaign=Campaign.create(
                "Асуна выросла у моря и ищет пропавшего брата. Носит серый дорожный плащ."
            ),
        )
        baseline = session.to_dict()
        report["baseline_session"] = baseline
        for model in models:
            run = run_conversation(request, baseline, model)
            report["comparison"].append(run)
            if run.get("error"):
                break
            if len(models) > 1 and not run.get("error"):
                # Do not keep both candidates resident on a 16 GB Windows computer.
                try:
                    unloaded = request("/api/generate", {"model": model, "keep_alive": 0})
                    run["unload"] = unloaded.get("done_reason", "requested")
                except (OSError, ValueError, KeyError, TypeError) as error:
                    run["unload_error"] = str(error)
                    print("Не удалось выгрузить модель: " + str(error), flush=True)
                    break
        primary = report["comparison"][0]
        report["cases"] = primary["cases"]  # Preserve the single-model report contract.
        okay = primary["protocol_passed"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["error"] = str(error)
    report["protocol_passed"] = okay
    args.report_dir.mkdir(parents=True, exist_ok=True)
    path = args.report_dir / ("narrator-" + report["run_id"] + ".json")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    readable = path.with_suffix(".txt")
    with readable.open("x", encoding="utf-8") as stream:
        stream.write("Качество текста ожидает оценки человеком.\n")
        for skipped in report.get("comparison_skipped", ()):
            stream.write("Сравнение пропущено: модель не найдена — " + skipped + "\n")
        for run in report["comparison"]:
            stream.write("\nМодель: " + run["model"] + "\n")
            for case in run["cases"]:
                stream.write("\nИгрок: " + case["input"] + "\n")
                if case.get("local_clarification"):
                    stream.write(case["brief"]["clarification"] + "\n")
                for attempt in case["attempts"]:
                    stream.write(
                        "Попытка " + str(attempt["attempt"]) + ": " + attempt["validation"] + "\n"
                    )
                    stream.write(attempt.get("content", "") + "\n")
        if report.get("error"):
            stream.write("Ошибка: " + report["error"] + "\n")
        stream.write("\n" + "\n".join(RUBRIC) + "\n")
    print("\nОтчёт: " + str(path), flush=True)
    print("Тексты для чтения: " + str(readable), flush=True)
    print("Ограниченные проверки основной модели: " + ("пройдены" if okay else "не пройдены"))
    print("Литературное качество: НЕ ОЦЕНЕНО программой. Прочитайте ответы по четырём критериям:")
    for item in RUBRIC:
        print("- " + item)
    if report.get("error"):
        print("Ошибка: " + report["error"])
    return 0 if okay else 1


if __name__ == "__main__":
    raise SystemExit(main())
