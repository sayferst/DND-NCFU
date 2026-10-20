"""Actual loopback HTTP: image contract, redirects, errors, privacy and no retries."""

import base64
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from rpg_vkr.visuals.client import ImageError, ImagesTransport, normalized_png

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@contextmanager
def images_server(status=200, mode="base64", usage=None):
    records = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.do_POST()

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            records.append(
                (
                    self.command,
                    self.path,
                    self.headers.get("Authorization"),
                    json.loads(body) if body else None,
                )
            )
            if self.path == "/file.png":
                raw = PNG
            else:
                row = (
                    {"b64_json": base64.b64encode(PNG).decode()}
                    if mode == "base64"
                    else {"url": f"http://127.0.0.1:{self.server.server_port}/file.png"}
                )
                response = {"data": [row], "id": "receipt"}
                response.update({"usage": usage} if usage is not None else {"cost_rub": "0.75"})
                raw = json.dumps(response).encode()
            self.send_response(status)
            if status == 302:
                self.send_header("Location", "https://example.invalid/do-not-follow")
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", records
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("mode", ["base64", "url"])
def test_one_post_image_and_never_authenticate_download(qt_app, mode):
    with images_server(mode=mode) as (url, records):
        client = ImagesTransport(test_base=url)
        png, cost, receipt = client.generate(
            {"model": "m", "prompt": "pixel art", "n": 1}, "fake-key"
        )
        assert (
            png.startswith(b"\x89PNG") and cost == 750000 and json.loads(receipt)["id"] == "receipt"
        )
        assert len([r for r in records if r[0] == "POST"]) == 1
        assert records[0][2] == "Bearer fake-key"
        if mode == "url":
            assert records[1][2] is None


@pytest.mark.parametrize("status", [302, 400, 401, 402, 429, 500])
def test_error_and_redirect_never_retry_or_echo_key(status):
    with images_server(status=status) as (url, records):
        with pytest.raises(ImageError) as caught:
            ImagesTransport(test_base=url).generate({"n": 1}, "fake-key")
        assert len(records) == 1 and "fake-key" not in str(caught.value)


def test_html_and_private_urls_rejected(qt_app):
    with pytest.raises(ImageError):
        normalized_png(b"<html>not an image</html>")
    client = ImagesTransport()
    for url in ["file:///secrets", "http://example.org/a.png", "https://127.0.0.1/x"]:
        with pytest.raises(ImageError):
            client.download(url)
