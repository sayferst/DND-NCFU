"""Real loopback HTTP, atomic quotas and hostile client input; upstream is a local fake."""

import base64
import json
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from server.gateway import FLUX, RECRAFT, TEXT_MODEL, Denied, Gateway, Server, Store


class FakeUpstream:
    def __init__(self):
        self.posts = []
        self.fail = False

    def request(self, route, body=None):
        if route == "models":
            return {
                "data": [
                    {
                        "id": TEXT_MODEL,
                        "context_length": 1048576,
                        "pricing": {"prompt": 0.00001, "completion": 0.00002},
                        "pricing_units": {"prompt": "token", "completion": "token"},
                    },
                    *[
                        {
                            "id": model,
                            "pricing": {"image_output": 1},
                            "pricing_units": {"image_output": "image"},
                            "image_pricing": [{"unit": "image", "variant": None, "price": 1}],
                            "supported_image_sizes": ["1K", "2K"],
                            "max_image_references": 8,
                            "supported_image_references": model == FLUX,
                        }
                        for model in (RECRAFT, FLUX)
                    ],
                    {"id": "unapproved/model"},
                ]
            }
        self.posts.append((route, body))
        if self.fail:
            raise Denied(503, "upstream_unavailable")
        if route == "images":
            return {"data": [{"b64_json": base64.b64encode(b"fakePNG").decode()}], "cost_rub": 1}
        return {
            "choices": [{"message": {"content": "Ответ"}, "finish_reason": "stop"}],
            "model": TEXT_MODEL,
            "usage": {"prompt_tokens": 5},
            "cost_rub": 0.01,
        }


def body():
    return {
        "model": TEXT_MODEL,
        "messages": [{"role": "user", "content": "Мир"}],
        "max_tokens": 65536,
        "stream": False,
    }


@contextmanager
def running(tmp_path):
    store = Store(tmp_path / "access.sqlite3", 100_000_000)
    token = store.issue("one", budget=50_000_000, worlds=2)
    upstream = FakeUpstream()
    gateway = Gateway(store, upstream)
    server = Server(("127.0.0.1", 0), gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/api/v1", token, store, upstream, gateway
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def request(base, token, route, value=None, identity="a" * 20, stage="world_seed"):
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "X-Request-ID": identity,
        "X-DND-Stage": stage,
    }
    req = urllib.request.Request(
        base + "/" + route,
        data=json.dumps(value).encode() if value is not None else None,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as reply:
            return reply.status, json.load(reply)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, json.load(error)


def test_real_http_auth_generation_duplicates_revocation_and_filtered_catalog(tmp_path):
    with running(tmp_path) as (base, token, store, upstream, _):
        assert request(base, "bad", "chat/completions", body())[0] == 401
        assert not upstream.posts
        status, result = request(base, token, "models")
        assert status == 200 and len(result["data"]) == 3
        assert request(base, token, "chat/completions", body())[0] == 200
        assert request(base, token, "chat/completions", body())[0] == 409
        assert len(upstream.posts) == 1
        store.revoke("one")
        assert request(base, token, "key")[0] == 401
        assert request(base, token, "chat/completions", body(), identity="b" * 20)[0] == 401
        assert token.encode() not in store.path.read_bytes()


@pytest.mark.parametrize(
    "edit",
    [
        {"model": "unapproved/model"},
        {"max_tokens": 65537},
        {"stream": True},
        {"tools": [{}]},
        {"provider": {"order": ["expensive"]}},
        {"max_tokens": True},
        {"messages": [{"role": "user", "content": [{"image_url": "http://localhost"}]}]},
    ],
)
def test_untrusted_parameters_cannot_reach_paid_upstream(tmp_path, edit):
    with running(tmp_path) as (base, token, _, upstream, _):
        assert request(base, token, "chat/completions", body() | edit)[0] == 400
        assert not upstream.posts


def test_atomic_global_and_individual_reservation_pending_and_world_quota(tmp_path):
    store = Store(tmp_path / "db", global_budget=1000)
    one = store.issue("one", budget=700, worlds=1)
    two = store.issue("two", budget=700, worlds=1)

    def reserve(pair):
        token, letter = pair
        try:
            return store.reserve(token, letter * 20, 700, "world_seed")
        except Denied as error:
            return error.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(reserve, [(one, "a"), (two, "b")]))
    assert results.count("budget_exhausted") == 1
    winner = "one" if "one" in results else "two"
    token, identity = (one, "a" * 20) if winner == "one" else (two, "b" * 20)
    store.settle(winner, identity, 10, succeeded=True)
    with pytest.raises(Denied, match="world_limit"):
        store.reserve(token, "c" * 20, 100, "world_seed")
    store.reserve(token, "d" * 20, 100, "director")
    with pytest.raises(Denied, match="request_in_progress"):
        store.reserve(token, "e" * 20, 100, "director")


def test_failed_request_keeps_reserve_and_actual_overrun_halts_service(tmp_path):
    with running(tmp_path) as (base, token, store, upstream, _):
        upstream.fail = True
        assert request(base, token, "chat/completions", body())[0] == 503
        assert store.summary()[0]["committed"] > 0
        assert request(base, token, "chat/completions", body())[0] == 409
        assert len(upstream.posts) == 1
        user = store.reserve(token, "z" * 20, 1, "director")
        store.settle(user, "z" * 20, 2, succeeded=True)
        with pytest.raises(Denied, match="billing_review_required"):
            store.reserve(token, "w" * 20, 1, "director")


def test_images_and_reference_urls_are_server_validated(tmp_path):
    with running(tmp_path) as (base, token, _, upstream, _):
        image = {"model": FLUX, "prompt": "Портрет", "n": 1, "resolution": "1K"}
        assert request(base, token, "images", image, stage="image")[0] == 200
        forged = image | {
            "input_references": [
                {"type": "image_url", "image_url": {"url": "http://127.0.0.1/secret"}}
            ]
        }
        assert request(base, token, "images", forged, identity="b" * 20, stage="image")[0] == 400
        assert len(upstream.posts) == 1


def test_expiry_uses_server_clock_and_restart_retains_quota(tmp_path):
    clock = [1.0]
    store = Store(tmp_path / "db", clock=lambda: clock[0])
    token = store.issue("one", days=1)
    store.reserve(token, "r" * 20, 500, "world_seed")
    restored = Store(store.path, clock=lambda: clock[0])
    assert restored.summary()[0]["committed"] == 500
    clock[0] = 86402
    with pytest.raises(Denied, match="expired"):
        restored.identity(token)
