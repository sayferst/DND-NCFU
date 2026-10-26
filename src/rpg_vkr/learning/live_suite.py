"""Explicit paired live checks on real game states, with a shared reserved budget."""

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal

from rpg_vkr.learning.library import Library, active_path
from rpg_vkr.learning.live_probe import MAX_OUTPUT, MODEL, request, upper_cost
from rpg_vkr.learning.probe_cases import PRIVATE_DIARY, PRIVATE_PLOT, cases
from rpg_vkr.learning.runtime import enrich
from rpg_vkr.narrative.cloud import CloudProfile, normalize_completion
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.routerai import CATALOG_URL, KEY_URL, parse_allowance, parse_models
from rpg_vkr.narrative.story import story_context, story_payload, story_proposal

# The preceding pilot reserved 3.8625 rubles. Even reserving all146 here remains <150.
MAX_SUITE_RUB = Decimal("146")


def fingerprint(session):
    return hashlib.sha256(
        json.dumps(
            [session.to_dict(), session.dice.checkpoint()],
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()


def prepare(directory):
    jobs = []
    for case in cases():
        session, query = case["session"], case["query"]
        before = fingerprint(session)
        frame = build_frame(session)
        for mode in ("B0", "B3"):
            session._learning_flags = {"library": mode == "B3", "memory": mode == "B3"}
            session._rag_mode = 2 if mode == "B3" else 0
            campaign = campaign_context(session, query=query)
            features = campaign.pop("learning_features", {})
            context = story_context(
                frame, MODEL, query, campaign=campaign, confirmed=case["confirmed"]
            )
            context["obstacle"] = case["obstacle"]
            if features:
                context = enrich(context, query, features, directory=directory, remote=True)
            local = story_payload(frame, MODEL, query, context=context)
            local["options"]["num_predict"] = MAX_OUTPUT
            serialized = json.dumps(local, ensure_ascii=False)
            if PRIVATE_DIARY in serialized or PRIVATE_PLOT in serialized:
                raise AssertionError("Закрытые сведения попали в запрос.")
            jobs.append(
                {
                    "case": case["id"],
                    "mode": mode,
                    "query": query,
                    "local": local,
                    "frame": frame,
                    "context": context,
                    "session": session,
                    "before": before,
                }
            )
        if fingerprint(session) != before:
            raise AssertionError("Сборка запроса изменила Session или RNG.")
    return jobs


def run_one(job, payload, profile):
    started = time.perf_counter()
    row = {
        "case": job["case"],
        "mode": job["mode"],
        "request_model": MODEL,
        "state_fingerprint": job["before"],
        "input_bytes": len(json.dumps(payload["messages"], ensure_ascii=False).encode()),
        "selected_ids": [r["id"] for r in job["context"].get("narrative_techniques", [])],
        "memory_events": len(job["context"].get("learning_memory", [])),
    }
    try:
        data = request(profile.endpoint, key=profile.key, payload=payload)
        normalized = normalize_completion(data)
        row.update(
            response_model=normalized.get("response_model"),
            usage=data.get("usage"),
            finish_reason=normalized.get("done_reason"),
            response=(normalized.get("message", {}).get("content") or "")[:16000],
        )
        try:
            story_proposal(normalized, job["frame"], job["query"], context=job["context"])
            row["status"] = "ACCEPTED"
        except ValueError as error:
            row.update(status="REJECTED_BY_GAME_VALIDATOR", reason=str(error)[:500])
    except ValueError as error:
        row.update(status="API_ERROR_NO_RETRY", reason=str(error)[:200])
    row["latency_ms"] = (time.perf_counter() - started) * 1000
    return row


def run(
    key, directory, *, budget=Decimal("5"), emit=lambda row: None, case_ids=(), max_output=1024
):
    if (
        not isinstance(budget, Decimal)
        or not budget.is_finite()
        or not Decimal(0) < budget <= MAX_SUITE_RUB
    ):
        raise ValueError("Бюджет расширенного прогона должен быть в пределах146₽.")
    if type(max_output) is not int or not 128 <= max_output <= 2048:
        raise ValueError("Предел выхода расширенной проверки128–2048токенов.")
    with Library(active_path(directory)) as db:
        pipeline = db.metadata["pipeline"]
    quotes = parse_models(request(CATALOG_URL))
    quote = next((q for q in quotes if q.id == MODEL), None)
    if quote is None or "max_tokens" not in quote.supported_parameters:
        raise ValueError("Точная модель или ограничение выхода не подтверждены.")
    allowance = parse_allowance(request(KEY_URL, key=key))
    cap = min(budget, allowance.remaining, max(Decimal(0), Decimal(1000) - allowance.used_monthly))
    if cap <= 0:
        raise ValueError("Проверка остановлена месячным бюджетом.")
    profile = CloudProfile("routerai", MODEL, key, supported_parameters=quote.supported_parameters)
    jobs = prepare(directory)
    if not set(case_ids) <= {job["case"] for job in jobs}:
        raise ValueError("Неизвестный сценарий проверки.")
    if case_ids:
        jobs = [job for job in jobs if job["case"] in case_ids]
    reserved, rows, pending = Decimal(0), [], []
    # Reserve sequentially before concurrency; no callback can spend beyond this ledger.
    for job in jobs:
        job["local"]["options"]["num_predict"] = max_output
        payload = profile.payload(job["local"])
        if "reasoning_effort" in quote.supported_parameters:
            payload["reasoning_effort"] = "low"
        cost = upper_cost(payload, quote)
        if reserved + cost > cap:
            row = {"case": job["case"], "mode": job["mode"], "status": "SKIPPED_BUDGET"}
            rows.append(row)
            emit(row)
        else:
            reserved += cost
            pending.append((job, payload, cost))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            pool.submit(run_one, job, payload, profile): cost for job, payload, cost in pending
        }
        for future in as_completed(futures):
            row = future.result()
            row["reserved_rub"] = str(futures[future])
            rows.append(row)
            emit(row)
    unchanged = all(fingerprint(job["session"]) == job["before"] for job in jobs)
    return {
        "status": "COMPLETED",
        "model": MODEL,
        "pipeline": pipeline,
        "scenarios": len({job["case"] for job in jobs}),
        "planned_generations": len(jobs),
        "sent_generations": len(pending),
        "workers": 2,
        "max_output_tokens": max_output,
        "cap_rub": str(cap),
        "reserved_upper_rub": str(reserved),
        "canonical_state_and_rng_unchanged": unchanged,
        "raw_corpus_sent": False,
        "private_plot_or_diary_in_requests": False,
        "weights_access": "INFERENCE_ONLY",
        "quality_gain": "NOT_ESTABLISHED_SMALL_LIVE_SAMPLE",
        "rows": sorted(rows, key=lambda r: (r["case"], r["mode"])),
    }
