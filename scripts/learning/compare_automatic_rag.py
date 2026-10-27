"""Budgeted DeepSeek-only A/B, identical committed scenes, no game-state mutations."""

import argparse
import hashlib
import json
import os
import sys
import time
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rpg_vkr.domain.adventure import offline_world
from rpg_vkr.domain.campaign import Campaign
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.unified import CLASSES
from rpg_vkr.learning.corpus import diagnostics
from rpg_vkr.learning.live_probe import MODEL, request, upper_cost
from rpg_vkr.narrative.cloud import CloudProfile, normalize_completion
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.routerai import CATALOG_URL, KEY_URL, parse_allowance, parse_models
from rpg_vkr.narrative.story import story_context, story_payload, story_proposal
from rpg_vkr.unified_session import UnifiedSession


def compare(key, output, prior=Decimal("38.29")):
    quote = next(q for q in parse_models(request(CATALOG_URL)) if q.id == MODEL)
    allowance = parse_allowance(request(KEY_URL, key=key))
    if not prior.is_finite() or not 0 <= prior < 150:
        raise ValueError("No cumulative budget remains")
    cap = min(Decimal("15"), allowance.remaining, Decimal(150) - prior)
    profile = CloudProfile("routerai", MODEL, key, supported_parameters=quote.supported_parameters)
    s = UnifiedSession.create(
        Character(**dict(zip(ABILITY_NAMES, CLASSES["mage"][3], strict=True))),
        "mage",
        "focus",
        seed=37,
        content_revision=2,
        campaign=replace(Campaign.create("", ""), world_id="00000000-0000-4000-8000-000000000037"),
    )
    s.start_world(offline_world(s))
    s.perform_gameplay("cast", {"spell": "light", "target": "hero"}, "actual-light")
    frame = build_frame(s)
    before = s.to_dict(), s.dice.checkpoint()
    cases = (
        (
            "inspection",
            "Мастер, осматриваю мастерскую: как выглядит кузнечный верстак? Ничего не беру.",
        ),
        (
            "confirmed_magic",
            "Мастер, опиши только подтверждённое применение света и моё окружение.",
        ),
        ("agency", "Я спрашиваю об условиях поручения и ещё не согласился. Что мне отвечают?"),
        ("memory", "Мастер, что уже произошло? Не добавляй новых событий."),
    )
    report = {
        "model": MODEL,
        "corpus": diagnostics(),
        "previous_task_reserved_rub": str(prior),
        "current_cap_rub": str(cap),
        "user_total_cap_rub": "150",
        "local_base": "BLOCKED_NO_WEIGHTS",
        "trained_local": "BLOCKED_NO_TRAINED_ADAPTER",
        "training_started": False,
        "rows": [],
    }
    reserved = Decimal(0)
    for case, query in cases:
        complete = story_context(
            frame,
            MODEL,
            query,
            campaign=campaign_context(s, query=query),
            history=[
                {"player": t.action, "result": t.text, "source": "rules"} for t in s.turns[-3:]
            ],
            confirmed=case == "confirmed_magic",
        )
        for mode in ("without_rag", "automatic_rag"):
            context = deepcopy(complete)
            if mode == "without_rag":
                for k in (
                    "archive_references",
                    "archive_reference_policy",
                    "narrative_techniques",
                    "learning_memory",
                    "learning_features",
                ):
                    context.pop(k, None)
            local = story_payload(frame, MODEL, query, context=context)
            local["options"]["num_predict"] = 1024
            payload = profile.payload(local)
            if "reasoning_effort" in quote.supported_parameters:
                payload["reasoning_effort"] = "low"
            bound = upper_cost(payload, quote)
            row = {
                "case": case,
                "mode": mode,
                "archive_ids": [r["id"] for r in context.get("archive_references", [])],
                "reserved_rub": str(bound),
                "player_message": query,
                "messages": payload["messages"],
                "prompt_sha256": hashlib.sha256(
                    json.dumps(payload["messages"], ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest(),
            }
            if reserved + bound > cap:
                row["status"] = "SKIPPED_BUDGET"
                report["rows"].append(row)
                continue
            reserved += bound
            row["status"] = "RESERVED_BEFORE_REQUEST"
            report["rows"].append(row)
            report["reserved_upper_rub"] = str(reserved)
            # Persist reservation even if the process is interrupted during a paid request.
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            started = time.perf_counter()
            try:
                raw = request(profile.endpoint, key=key, payload=payload)
                response = normalize_completion(raw)
                row.update(
                    response_model=response.get("response_model"),
                    usage=raw.get("usage"),
                    response=response.get("message", {}).get("content", ""),
                    finish_reason=response.get("done_reason"),
                )
                try:
                    story_proposal(response, frame, query, context=context)
                    row["status"] = "ACCEPTED_BY_GAME_VALIDATOR"
                except ValueError as error:
                    row.update(status="REJECTED_BY_GAME_VALIDATOR", reason=str(error)[:400])
            except ValueError as error:
                row.update(status="API_ERROR_NO_RETRY", reason=str(error)[:250])
            row["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report.update(
        canonical_state_and_rng_unchanged=before == (s.to_dict(), s.dice.checkpoint()),
        quality_claim=(
            "Small engineering sample; "
            "no blind literary quality or long-narrative superiority claim"
        ),
    )
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {k: v for k, v in report.items() if k != "rows"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--prior-reserved-rub", type=Decimal, default=Decimal("38.29"))
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Use a new report filename")
    if not args.execute:
        print(json.dumps({"paid_requests": 0, "max_reserved_rub": 15, "model": MODEL}))
    else:
        key = (
            args.key_file.read_text().strip()
            if args.key_file
            else os.environ.get("DND_ROUTERAI_API_KEY", "")
        )
        print(json.dumps(compare(key, args.output, args.prior_reserved_rub), ensure_ascii=False))
