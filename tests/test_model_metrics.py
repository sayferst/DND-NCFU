"""Bounded real loopback requests and durable counters, not DeepSeek quality evidence."""

import json
import sqlite3
from contextlib import closing
from copy import deepcopy

from response_cases import new_session
from test_catalog_ui import LOOK, creation
from test_local_narrator import local_server, wait_for
from test_routerai import configure, router_server

from rpg_vkr.application import Session
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.ollama import OllamaClient
from rpg_vkr.storage.campaigns import CampaignRepository


def post_count(calls):
    return sum(c["method"] == "POST" for c in calls)


def test_response_events_are_persisted_once_with_usage_and_no_prompts(window, qt_app, monkeypatch):
    window._session = new_session()
    message = "Веста, привет"
    plan = {
        "steps": [],
        "places": [],
        "check": "none",
        "dialogue_target": "vesta",
        "reply": "«Здравствуй», — отвечает Веста.",
    }
    with router_server(world_plans={message: plan}) as (url, calls):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        window.action_input.setText(message)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        events = window.ollama.events
        assert [e["event_type"] for e in events] == ["model_response", "prose_validation"]
        assert events[0]["usage"] == {"input_tokens": 320, "output_tokens": 75, "total_tokens": 395}
        assert events[0]["finish_reason"] == "stop" and events[0]["elapsed_ms"] >= 0
        assert post_count(calls) == 1
        db = CampaignRepository(window._campaign_repository.path)
        stats = db.model_stats(window._session)
        assert sum(r["count"] for r in stats) == 2
        # A duplicated notification cannot become a second charged request in statistics.
        db.record_model_call(window._session, events[0])
        assert db.model_stats(window._session) == stats
        with closing(sqlite3.connect(db.path)) as connection:
            raw = connection.execute("SELECT payload FROM model_calls").fetchall()
        text = str(raw)
        assert (
            message not in text and "routerai-test-key" not in text and "Authorization" not in text
        )
        assert "генераций 1" in window.narrator_metrics.text()
        assert sum(r["count"] for r in db.model_stats(Session())) == 0


def test_budget_is_shared_by_search_plan_and_writer_and_never_replays_creation(
    window, qt_app, monkeypatch
):
    query = {"steps": [], "places": [], "check": "none", "queries": ["mat_copper"]}
    with router_server(world_plans={LOOK: [query, creation()]}, writer_text="走近") as (url, calls):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        window.action_input.setText(LOOK)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert post_count(calls) == 3
        assert window.ollama.request_count == 3
        assert len(window._session.turns) == 1 and window._session.turns[0].catalog
        assert len(window._session.catalog.entities) > 0
        assert window._session.dice.checkpoint()[1] == 0
        assert [
            e["attempt"] for e in window.ollama.events if e["event_type"] == "model_response"
        ] == [1, 2, 3]
        assert window.ollama.events[-1]["outcome"] == "rejected"
        assert Session.from_dict(window._session.to_dict()).to_dict() == window._session.to_dict()


def test_inline_false_reward_is_rejected_without_becoming_state(window, qt_app, monkeypatch):
    window._session = new_session()
    before = window._session.world, window._session.dice.checkpoint()
    text = "Веста, привет"
    bad = {"steps": [], "places": [], "check": "none", "reply": "Вы получили 100 золотых."}
    with router_server(world_plans={text: bad}, writer_text="«Здравствуй», — отвечает Веста.") as (
        url,
        calls,
    ):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        window.action_input.setText(text)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert post_count(calls) == 2
        assert (window._session.world, window._session.dice.checkpoint()) == before
        validations = [e for e in window.ollama.events if e["event_type"] == "prose_validation"]
        assert len(validations) == 1 and validations[0]["outcome"] == "rejected"
        assert "100" not in window._session.narrations[-1].text


def test_new_npc_and_reply_register_then_persist_in_one_post(window, qt_app, monkeypatch):
    window._session = Session(seed=5)
    plan = creation() | {
        "reply": "Мира откладывает инструменты. «Здравствуйте».",
        "dialogue_target": "mira",
    }
    with router_server(world_plans={LOOK: plan}) as (url, calls):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        window.action_input.setText(LOOK)
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert post_count(calls) == 1
        assert len(window._session.turns) == 2
        assert window._session.turns[-1].actor_id == "mira"
        assert window._session.turns[0].catalog
        assert Session.from_dict(window._session.to_dict()).to_dict() == window._session.to_dict()


def test_network_failure_is_not_retried_and_unknown_usage_is_not_zero(window, qt_app, monkeypatch):
    with router_server(chat_status=503) as (url, calls):
        configure(window, monkeypatch, url)
        window.world_agent.setChecked(True)
        before = deepcopy(window._session.to_dict())
        window.action_input.setText("Веста, здравствуйте")
        window.send_button.click()
        wait_for(qt_app, lambda: not window.ollama.busy)
        assert post_count(calls) == 1
        assert window._session.to_dict() == before
        assert window.action_input.text() == "Веста, здравствуйте"
        event = window.ollama.events[-1]
        assert event["outcome"] == "failed" and event["code"] == "network"
        assert event["usage"] is None


def test_cancel_and_direct_budget_enforcement_count_actual_posts_only(qt_app):
    with local_server(mode="plain_always_bad", delay=0.05) as (url, calls):
        client = OllamaClient(base_url=url)
        client.models = ("local-test:1",)
        client.begin_turn()
        # Reject both initial reply and repair; a further call has only one remaining POST.
        client.develop(build_frame(Session()), "local-test:1", "где я?", memory={}, campaign={})
        wait_for(qt_app, lambda: not client.busy)
        assert client.request_count == 2
        client.develop(build_frame(Session()), "local-test:1", "где я?", memory={}, campaign={})
        wait_for(qt_app, lambda: not client.busy)
        assert len(calls) == 3 and client.request_count == 3
        client.develop(build_frame(Session()), "local-test:1", "где я?", memory={}, campaign={})
        wait_for(qt_app, lambda: not client.busy)
        assert len(calls) == 3 and client.last_failure["code"] == "request_budget"
        client.begin_turn()
        client.develop(build_frame(Session()), "local-test:1", "где я?", memory={}, campaign={})
        wait_for(qt_app, lambda: bool(calls) and len(calls) == 4)
        client.cancel()
        assert client.events[-1]["outcome"] == "cancelled"
        assert len([e for e in client.events if e["event_type"] == "model_response"]) == 4
        assert all(e["usage"] is None for e in client.events)
        assert "content" not in json.dumps(client.events)
        client.deleteLater()
