"""Independent connection scenarios: real Qt/loopback GET, no paid generation."""

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from test_local_narrator import wait_for
from test_routerai import ALLOWANCE, MODEL, QUOTE

from rpg_vkr.narrative.routerai import RouterAIClient, parse_models


@contextmanager
def metadata_server(monkeypatch, *, catalog=None, status=200, key_status=200, delay=0):
    import rpg_vkr.narrative.routerai as api

    records = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            records.append((self.path, bool(self.headers.get("Authorization"))))
            key = self.path.endswith("/key")
            if delay:
                import time

                time.sleep(delay)
            body = (
                {"data": ALLOWANCE}
                if key
                else catalog
                if catalog is not None
                else {"data": [QUOTE]}
            )
            raw = json.dumps(body).encode()
            self.send_response(key_status if key else status)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(api, "CATALOG_URL", base + "/models")
    monkeypatch.setattr(api, "KEY_URL", base + "/key")
    try:
        yield records
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_catalog_keeps_text_model_when_price_is_unknown():
    (quote,) = parse_models({"data": [QUOTE | {"pricing_units": {}}]}, include_unpriced=True)
    assert quote.id == MODEL
    assert quote.prompt_rub is None and quote.completion_rub is None
    assert "не подтверждена" in quote.label
    assert "0.00" not in quote.label


def test_real_large_catalog_is_not_mistaken_for_invalid_key(qt_app, monkeypatch):
    row = QUOTE | {"description": "x" * (5 * 1024 * 1024)}
    with metadata_server(monkeypatch, catalog={"data": [row]}) as records:
        client = RouterAIClient()
        ready, errors = [], []
        client.catalog_ready.connect(ready.append)
        client.failed.connect(errors.append)
        client.list_models()
        wait_for(qt_app, lambda: bool(ready or errors))
        assert ready and not errors
        assert records == [("/models", False)]
