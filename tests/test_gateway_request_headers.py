"""Real HTTP wire regression: empty metadata GETs must not advertise a JSON body."""

import http.client
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from server.gateway import Upstream


@contextmanager
def strict_api():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.answer()

        def do_POST(self):
            self.answer()

        def answer(self):
            size = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(size)
            calls.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": raw,
                }
            )
            # Reproduce a strict JSON parser rejecting an advertised but missing body.
            status = (
                400 if self.headers.get_content_type() == "application/json" and not raw else 200
            )
            value = {"data": []} if self.path.endswith("/models") else {"data": {"disabled": False}}
            reply = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("route", ["key", "models"])
def test_metadata_empty_get_survives_strict_json_parser(monkeypatch, route):
    with strict_api() as (port, calls):
        monkeypatch.setattr(
            "server.gateway.http.client.HTTPSConnection",
            lambda host, timeout: http.client.HTTPConnection("127.0.0.1", port, timeout=timeout),
        )
        result = Upstream("test-owner-key").request(route)
        assert "data" in result
        assert len(calls) == 1 and calls[0]["method"] == "GET" and calls[0]["body"] == b""
        assert calls[0]["path"] == "/api/v1/" + route
        headers = calls[0]["headers"]
        assert headers["Accept"] == "application/json" and "Content-Type" not in headers
        if route == "models":
            assert "Authorization" not in headers
        else:
            assert headers["Authorization"] == "Bearer test-owner-key"


@pytest.mark.parametrize("route", ["chat/completions", "images"])
def test_generation_keeps_json_body_and_auth_with_one_post(monkeypatch, route):
    with strict_api() as (port, calls):
        monkeypatch.setattr(
            "server.gateway.http.client.HTTPSConnection",
            lambda host, timeout: http.client.HTTPConnection("127.0.0.1", port, timeout=timeout),
        )
        value = {"model": "local-fixture-only", "prompt": "Только локальная проверка"}
        assert Upstream("test-owner-key").request(route, value)
        assert len(calls) == 1 and calls[0]["method"] == "POST"
        assert json.loads(calls[0]["body"]) == value
        assert calls[0]["headers"]["Content-Type"] == "application/json"
        assert calls[0]["headers"]["Accept"] == "application/json"
        assert calls[0]["headers"]["Authorization"] == "Bearer test-owner-key"
