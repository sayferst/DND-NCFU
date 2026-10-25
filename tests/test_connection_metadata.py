"""Independent connection scenarios: real Qt/loopback GET, no paid generation."""

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
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
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
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


@pytest.mark.parametrize("key", ["Bearer sk-test", "sk-\n-header", "ключ", "x" * 4097, ""])
def test_bad_key_format_makes_no_http_request(qt_app, monkeypatch, key):
    with metadata_server(monkeypatch) as records:
        client = RouterAIClient()
        errors = []
        client.failed.connect(errors.append)
        client.check_key(key)
        assert len(errors) == 1 and not client.busy and not records
        assert "API-ключ" in errors[0]
        assert errors[0] == (
            "Укажите API-ключ провайдера без пробелов, переносов и префикса Bearer; "
            "не пароль ChatGPT."
        )


@pytest.mark.parametrize("units", [{}, {"prompt": "request", "completion": "token"}])
def test_unpriced_catalog_does_not_invent_token_prices(units):
    (quote,) = parse_models({"data": [QUOTE | {"pricing_units": units}]}, include_unpriced=True)
    assert quote.id == MODEL and quote.prompt_rub is None and "₽/млн" not in quote.label


def test_unpriced_mode_still_rejects_image_only_models():
    with pytest.raises(ValueError):
        parse_models(
            {"data": [QUOTE | {"architecture": {"output_modalities": ["image"]}}]},
            include_unpriced=True,
        )
