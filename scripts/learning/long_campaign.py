"""Opt-in actual DeepSeek campaign with durable cumulative cap; no training or retries."""

import argparse
import getpass
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from rehearse_class_campaign import genesis  # noqa: E402

from rpg_vkr.application import Session  # noqa: E402
from rpg_vkr.learning.live_probe import MODEL, request, upper_cost  # noqa: E402
from rpg_vkr.learning.spend_journal import SpendJournal  # noqa: E402
from rpg_vkr.narrative.cloud import CloudProfile, normalize_completion  # noqa: E402
from rpg_vkr.narrative.context import build_frame  # noqa: E402
from rpg_vkr.narrative.master import campaign_context  # noqa: E402
from rpg_vkr.narrative.records import Narration  # noqa: E402
from rpg_vkr.narrative.routerai import (  # noqa: E402
    CATALOG_URL,
    KEY_URL,
    parse_allowance,
    parse_models,
)
from rpg_vkr.narrative.story import story_context, story_payload, story_proposal  # noqa: E402
from rpg_vkr.storage.campaigns import CampaignRepository  # noqa: E402
from rpg_vkr.storage.slots import SaveSlots  # noqa: E402

PRIOR = Decimal("51.43295335334804")


def step(s, index):
    command, args, text = (
        "check",
        {"task": ("perception", "knowledge", "survival", "stealth")[index % 4], "dc": 10},
        "Осматриваюсь и проверяю, что могу заметить в этом месте.",
    )
    if index % 12 == 0:
        command, args, text = "rest", {}, "Отдыхаю перед дорогой."
    elif index % 12 == 1 and s.gameplay["mp"] >= 2:
        command, args, text = "cast", {"spell": "light", "target": "hero"}, "Создаю свет."
    elif index % 12 == 2:
        place = s.interaction_state().current
        if s.gameplay["living_world"]["nodes"][place].get("mat_2_0", 0):
            command, args, text = (
                "gather",
                {"material": "mat_2_0", "quantity": 1},
                "Собираю лечебные травы.",
            )
    elif index % 12 == 3:
        command, args, text = (
            "wait",
            {"minutes": 60},
            "Наблюдаю за жизнью поселения в течение часа.",
        )
    elif index % 12 == 4:
        command, args, text = (
            "travel",
            {"destination": "path" if s.interaction_state().current == "pier" else "pier"},
            "Иду по знакомой дороге.",
        )
    try:
        s.perform_gameplay(command, args, s._request_token())
    except ValueError:
        if command != "travel":
            raise
        command, args, text = "wait", {"minutes": 60}, "Жду открытия перекрытой дороги."
        s.perform_gameplay(command, args, s._request_token())
    return text + " Опиши подтверждённый результат кратко, в 1–3 предложениях."


def execute(key, output, turns, controls, prior, cap):
    output.mkdir(parents=True, exist_ok=False)
    quote = next(q for q in parse_models(request(CATALOG_URL)) if q.id == MODEL)
    if "max_tokens" not in quote.supported_parameters:
        raise ValueError("Output limit not supported by the exact model")
    allowance = parse_allowance(request(KEY_URL, key=key))
    cap = min(cap, prior + allowance.remaining)
    ledger = SpendJournal(output / "spend.json", prior, cap)
    profile = CloudProfile("routerai", MODEL, key, supported_parameters=quote.supported_parameters)
    s = genesis("mage", 37)
    started = time.perf_counter()
    rows, pairs = output / "responses.jsonl", output / "pending-engine-pairs.jsonl"
    completed = 0
    stop_reason = "COMPLETED"
    with ThreadPoolExecutor(max_workers=2) as pool:
        for index in range(turns):
            query = step(s, index)
            frame = build_frame(s)
            public = campaign_context(s, query=query)
            context = story_context(
                frame,
                MODEL,
                query,
                campaign=public,
                confirmed=True,
                history=[
                    {"player": t.action, "result": t.text, "source": "rules"} for t in s.turns[-4:]
                ],
            )
            jobs = []
            for mode in ["automatic_rag", "without_rag"] if index < controls else ["automatic_rag"]:
                current = deepcopy(context)
                if mode == "without_rag":
                    for name in (
                        "archive_references",
                        "archive_reference_policy",
                        "narrative_techniques",
                        "learning_memory",
                        "learning_features",
                    ):
                        current.pop(name, None)
                local = story_payload(frame, MODEL, query, context=current)
                local["options"]["num_predict"] = 512
                payload = profile.payload(local)
                if "reasoning_effort" in quote.supported_parameters:
                    payload["reasoning_effort"] = "low"
                identifier = f"turn-{index + 1:04}-{mode}"
                bound = upper_cost(payload, quote)
                if ledger.accounted + bound > ledger.cap:
                    stop_reason = "CUMULATIVE_BUDGET_STOP"
                    break
                ledger.reserve(identifier, bound)
                jobs.append(
                    (
                        identifier,
                        mode,
                        current,
                        pool.submit(request, profile.endpoint, key=key, payload=payload),
                    )
                )
            if not jobs:
                break
            for identifier, mode, current, future in jobs:
                row = {"id": identifier, "turn": len(s.turns), "mode": mode, "model": MODEL}
                raw, proposal = None, None
                try:
                    raw = future.result()
                    ledger.settle(identifier, raw.get("usage"), quote)
                    response = normalize_completion(raw)
                    if response.get("response_model") != MODEL:
                        raise ValueError("Unexpected provider model; no fallback is authorized")
                    row.update(
                        response_model=response.get("response_model"),
                        usage=raw.get("usage"),
                        response=response.get("message", {}).get("content", ""),
                        finish_reason=response.get("done_reason"),
                    )
                    try:
                        proposal = story_proposal(response, frame, query, context=current)
                        row["status"] = "ACCEPTED_BY_GAME_VALIDATOR"
                    except ValueError as error:
                        row.update(status="REJECTED_BY_GAME_VALIDATOR", reason=str(error)[:400])
                except ValueError as error:
                    row.update(status="API_OR_ACCOUNTING_ERROR_NO_RETRY", reason=str(error)[:250])
                with rows.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                if proposal and mode == "automatic_rag":
                    pair = {
                        "schema_version": "live-engine-pair-v1",
                        "sample_id": identifier,
                        "campaign_id": "authored-sequential-live-mage-37",
                        "query": query,
                        "public_context": current,
                        "engine_receipt": s.turns[-1].gameplay["receipt"],
                        "gm_response": proposal.narration,
                        "review_status": "pending",
                        "rights_status": "unknown",
                        "training_admitted": False,
                        "provenance": (
                            "actual_engine_commands_and_live_provider_"
                            "authored_scenario_not_human_play"
                        ),
                    }
                    with pairs.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(pair, ensure_ascii=False) + "\n")
                    s.add_narration(
                        Narration(len(s.turns), MODEL, proposal.narration, frame.fingerprint)
                    )
            completed += 1
            if (index + 1) % 10 == 0:
                print(
                    json.dumps(
                        {"completed_turns": completed, "accounted_total_rub": str(ledger.accounted)}
                    ),
                    flush=True,
                )
            if any(r.get("status") == "QUOTE_BOUND_EXCEEDED" for r in ledger.rows):
                raise ValueError("Quote mismatch; no further requests allowed")
    slots = SaveSlots(output / "saves")
    slots.save(1, s)
    restored = slots.load(1)
    repository = CampaignRepository(output / "campaigns.sqlite3")
    repository.sync(s)
    assert restored.to_dict() == s.to_dict() == repository.load(repository.identity(s)).to_dict()
    assert restored.dice.checkpoint() == s.dice.checkpoint()
    assert (
        Session.from_dict(json.loads(json.dumps(s.to_dict())), version=31).dice.checkpoint()
        == s.dice.checkpoint()
    )
    report = {
        "model": MODEL,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "completed_turns": completed,
        "paired_control_states": sum(r["id"].endswith("without_rag") for r in ledger.rows),
        "requested_turns": turns,
        "stop_reason": stop_reason,
        "calls": len(ledger.rows),
        "accounted_total_rub": str(ledger.accounted),
        "prior_accounted_rub": str(prior),
        "prompt_rub_per_token": str(quote.prompt_rub),
        "completion_rub_per_token": str(quote.completion_rub),
        "json_sqlite_replay_rng_equal": True,
        "responses_sha256": hashlib.sha256(rows.read_bytes()).hexdigest(),
        "seconds": time.perf_counter() - started,
        "human_blind_review": False,
        "independent_scenes": False,
        "training_started": False,
        "conditions": (
            "One sequential authored noncombat campaign; paired controls share exact states. "
            "Automatic validators do not establish literary quality or "
            "complete freedom from hallucinations."
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--turns", type=int, default=500)
    parser.add_argument("--controls", type=int, default=100)
    parser.add_argument("--prior-accounted-rub", type=Decimal, default=PRIOR)
    parser.add_argument("--cumulative-cap-rub", type=Decimal, default=Decimal(150))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.turns <= 2000 or not 0 <= args.controls <= args.turns:
        parser.error("Invalid campaign bounds")
    if not args.execute:
        print(json.dumps({"paid_requests": 0, "planned_turns": args.turns, "model": MODEL}))
    else:
        key = getpass.getpass("RouterAI key (hidden, never saved): ")
        print(
            json.dumps(
                execute(
                    key,
                    args.output,
                    args.turns,
                    args.controls,
                    args.prior_accounted_rub,
                    args.cumulative_cap_rub,
                ),
                ensure_ascii=False,
            )
        )
