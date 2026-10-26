"""Small opt-in inference probe. Does not inspect, modify or train model weights."""

import json
import time
import urllib.error
import urllib.request
from decimal import Decimal

from rpg_vkr.application import Session
from rpg_vkr.domain.catalog import Definition, Entity
from rpg_vkr.domain.interactions import Step, WorldPlan
from rpg_vkr.learning.library import Library, active_path
from rpg_vkr.learning.runtime import enrich
from rpg_vkr.narrative.cloud import CloudProfile, normalize_completion, validate_api_key
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.routerai import CATALOG_URL, KEY_URL, parse_allowance, parse_models
from rpg_vkr.narrative.story import story_context, story_payload, story_proposal

MODEL = "deepseek/deepseek-v4.1-flash"
MAX_OUTPUT = 1024
MAX_SPEND = Decimal("5")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Перенаправление запроса с ключом запрещено.")


def request(url, *, key="", payload=None):
    if not url.startswith("https://routerai.ru/api/v1/"):
        raise ValueError("Проверка разрешена только через RouterAI.")
    headers = {"Accept": "application/json"}
    if key:
        validate_api_key(key)
        headers["Authorization"] = "Bearer " + key
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(
            urllib.request.Request(url, data=body, headers=headers), timeout=50
        ) as reply:
            raw = reply.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Слишком большой ответ API.")
        return json.loads(raw)
    except urllib.error.HTTPError as error:
        raise ValueError("RouterAI HTTP " + str(error.code)) from None
    except (urllib.error.URLError, TimeoutError):
        raise ValueError(
            "RouterAI: соединение не завершено; автоматического повтора нет."
        ) from None


def upper_cost(payload, quote):
    # Byte fallback is deliberately conservative; include framing overhead separately.
    inputs = len(json.dumps(payload["messages"], ensure_ascii=False).encode()) + 2048
    output = payload.get("max_tokens", payload.get("max_completion_tokens", MAX_OUTPUT))
    if type(output) is not int or not 1 <= output <= 4096:
        raise ValueError("Не подтверждён безопасный предел выхода.")
    return Decimal(inputs) * quote.prompt_rub + Decimal(output) * quote.completion_rub


def live_probe(key, directory, *, execute=False):
    if not execute:
        return {
            "status": "READY_NOT_RUN",
            "model": MODEL,
            "max_calls": 8,
            "max_reserved_rub": str(MAX_SPEND),
            "weights_access": "UNAVAILABLE_INFERENCE_ONLY",
        }
    with Library(active_path(directory)) as db:
        pipeline = db.metadata["pipeline"]
    quotes = parse_models(request(CATALOG_URL))
    quote = next((q for q in quotes if q.id == MODEL), None)
    if quote is None or "max_tokens" not in quote.supported_parameters:
        raise ValueError("Точная модель или ограничение выхода не подтверждены каталогом.")
    allowance = parse_allowance(request(KEY_URL, key=key))
    cap = min(
        MAX_SPEND, allowance.remaining, max(Decimal(0), Decimal(1000) - allowance.used_monthly)
    )
    if cap <= 0:
        raise ValueError("Нет бюджета для проверки в пределах1000₽/месяц.")
    profile = CloudProfile("routerai", MODEL, key, supported_parameters=quote.supported_parameters)
    session = Session(seed=37)
    place = session.interaction_state().current
    session.register_catalog(
        "Встречаю писца Ливну у дорожной доски",
        [
            Definition("pilot_scribe_type", "Ливна", "actor", ("npcs",), {"hp_max": 1}),
            Definition(
                "pilot_board_type",
                "Дорожная доска",
                "item",
                ("miscellaneous",),
                {"appearance": "На доске вырезан знак моста"},
            ),
        ],
        [
            Entity("pilot_scribe", "pilot_scribe_type", place, state={"hp": 1}),
            Entity("pilot_board", "pilot_board_type", place),
        ],
        "Оригинальная проверочная сцена",
        "owner-authorized-live-probe",
    )
    session.submit_interaction(
        "Осматриваю дорожную доску", WorldPlan((Step("look", "pilot_board"),))
    )
    questions = (
        ("inspection", "Мастер, осматриваю дорожную доску. Покупать или брать её не хочу."),
        ("voice", "Ливна, как вас зовут и чем вы заняты?"),
        ("agency", "Мастер, я только спрашиваю об условиях поручения и ещё не согласился."),
        ("memory", "Мастер, что я помню о встрече с Ливной и осмотре доски?"),
    )
    frame = build_frame(session)
    before = session.to_dict(), session.dice.checkpoint()
    reserved, rows = Decimal(0), []
    for case, query in questions:
        for mode in ("B0", "B3"):
            session._learning_flags = {"library": mode == "B3", "memory": mode == "B3"}
            session._rag_mode = 2 if mode == "B3" else 0
            campaign = campaign_context(session, query=query)
            features = campaign.pop("learning_features", {})
            context = story_context(frame, MODEL, query, campaign=campaign)
            if features:
                context = enrich(context, query, features, directory=directory, remote=True)
            local = story_payload(frame, MODEL, query, context=context)
            local["options"]["num_predict"] = MAX_OUTPUT
            payload = profile.payload(local)
            if "reasoning_effort" in quote.supported_parameters:
                payload["reasoning_effort"] = "low"
            bound = upper_cost(payload, quote)
            if reserved + bound > cap:
                rows.append({"case": case, "mode": mode, "status": "SKIPPED_BUDGET"})
                continue
            reserved += bound  # Reserve before POST, including unknown/timeout outcomes.
            started = time.perf_counter()
            row = {
                "case": case,
                "mode": mode,
                "request_model": MODEL,
                "reserved_rub": str(bound),
                "selected_ids": [r["id"] for r in context.get("narrative_techniques", [])],
            }
            try:
                data = request(profile.endpoint, key=key, payload=payload)
                normalized = normalize_completion(data)
                row["response_model"] = normalized.get("response_model")
                row["usage"] = data.get("usage")
                row["finish_reason"] = normalized.get("done_reason")
                raw = normalized.get("message", {}).get("content") or ""
                row["response"] = raw[:16000]
                try:
                    story_proposal(normalized, frame, query, context=context)
                    row["status"] = "ACCEPTED"
                except ValueError as error:
                    row["status"] = "REJECTED_BY_GAME_VALIDATOR"
                    row["reason"] = str(error)[:500]
            except ValueError as error:
                row["status"] = "API_ERROR_NO_RETRY"
                row["reason"] = str(error)[:200]
            row["latency_ms"] = (time.perf_counter() - started) * 1000
            rows.append(row)
    return {
        "status": "COMPLETED",
        "model": MODEL,
        "pipeline": pipeline,
        "max_reserved_rub": str(cap),
        "reserved_upper_rub": str(reserved),
        "max_output_tokens": MAX_OUTPUT,
        "prompt_rub_per_million": str(quote.prompt_rub * 1000000),
        "completion_rub_per_million": str(quote.completion_rub * 1000000),
        "canonical_state_and_rng_unchanged": before
        == (session.to_dict(), session.dice.checkpoint()),
        "raw_corpus_sent": False,
        "weights_access": "UNAVAILABLE_INFERENCE_ONLY",
        "training_started": False,
        "rows": rows,
    }
