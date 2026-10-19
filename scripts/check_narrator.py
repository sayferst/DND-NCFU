"""Exercise an actually installed local model; no downloads, GUI, paid API or user save writes."""

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rpg_vkr.application import Session  # noqa: E402
from rpg_vkr.domain.campaign import Campaign  # noqa: E402
from rpg_vkr.domain.character import Character
from rpg_vkr.domain.director import Proposal
from rpg_vkr.narrative.context import build_frame  # noqa: E402
from rpg_vkr.narrative.dialogue import last_interlocutor  # noqa: E402
from rpg_vkr.narrative.master import campaign_context  # noqa: E402
from rpg_vkr.narrative.records import PROMPT_VERSION  # noqa: E402
from rpg_vkr.narrative.story import (  # noqa: E402
    payload_context,
    repair_payload,
    story_payload,
    story_proposal,
)
from rpg_vkr.storage.knowledge import retrieve  # noqa: E402


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(
        description="Реальный тест локального рассказчика без изменения ячеек"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3:1.7b")
    parser.add_argument("--timeout", type=int, default=150)
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "DND-NCFU-data" / "diagnostics",
    )
    args = parser.parse_args()
    from urllib.parse import urlsplit

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
    opener = build_opener(ProxyHandler({}), NoRedirect())
    report = {
        "run_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"),
        "platform": platform.system(),
        "model": args.model,
        "seed": 42,
        "prompt_version": PROMPT_VERSION,
        "purpose": "sequential dialogue and heuristic content checks, not a literary quality score",
        "cases": [],
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
        if args.model not in {m["name"] for m in installed["models"]}:
            raise ValueError("Указанная модель не установлена. Ничего автоматически не скачано.")
        session = Session(
            seed=42,
            character=Character(name="Асуна"),
            campaign=Campaign.create(
                "Асуна выросла у моря, училась вести торговые записи и ищет пропавшего брата. "
                "Она осторожна с незнакомцами, носит серый дорожный плащ."
            ),
        )
        okay = True
        for text in (
            "подойду",
            "подойду к девушке",
            "спросить, как у нее дела",
            "спросить, нужна ли ей помощь, а заодно узнать ее имя",
            "как тебя зовут?",
        ):
            case = {"input": text, "attempts": []}
            report["cases"].append(case)
            history = [
                {
                    "player": t.action,
                    "result": t.text,
                    "source": t.scene.version if t.scene else "rules",
                }
                for t in session.turns[-3:]
            ]
            payload = story_payload(
                build_frame(session),
                args.model,
                text,
                memory=retrieve(session, text),
                campaign=campaign_context(session, last_interlocutor(session)),
                history=history,
            )
            context = payload_context(payload)
            case["brief"] = context["turn_brief"]
            if context["turn_brief"].get("clarification"):
                proposal = Proposal("", "", context["turn_brief"]["clarification"], ())
                session.submit_scene(
                    text, proposal, "local-clarification", base_turn=len(session.turns)
                )
                case["accepted"] = True
                case["local_clarification"] = True
                print("\nИгрок: " + text + "\nМастер: " + proposal.narration, flush=True)
                continue
            for attempt in range(2):
                answer = request("/api/chat", payload)
                raw = answer.get("message", {}).get("content", "")
                result = {
                    "attempt": attempt + 1,
                    "request": payload,
                    "content": raw[:6000],
                    "done_reason": answer.get("done_reason"),
                }
                case["attempts"].append(result)
                try:
                    proposal = story_proposal(
                        answer, build_frame(session), text, context=context, previous=history
                    )
                    session.submit_scene(text, proposal, args.model, base_turn=len(session.turns))
                    result["validation"] = "accepted"
                    print("\nИгрок: " + text + "\nМастер: " + proposal.narration, flush=True)
                    break
                except (ValueError, TypeError, KeyError) as error:
                    result["validation"] = str(error)
                    if attempt == 0:
                        payload = repair_payload(payload, error)
                    else:
                        okay = False
            case["accepted"] = case["attempts"][-1]["validation"] == "accepted"
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["error"] = str(error)
        okay = False
    report["protocol_passed"] = okay
    args.report_dir.mkdir(parents=True, exist_ok=True)
    path = args.report_dir / ("narrator-" + report["run_id"] + ".json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\nОтчёт: " + str(path), flush=True)
    print(
        "Разговор прошёл ограниченные проверки. Оцените содержание ответов выше."
        if okay
        else "Рассказчик не прошёл реальную проверку. Ошибка: " + report.get("error", "см. отчёт"),
        flush=True,
    )
    return 0 if okay else 1


if __name__ == "__main__":
    raise SystemExit(main())
