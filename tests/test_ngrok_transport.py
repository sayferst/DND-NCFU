"""Artist and owner health carry the ngrok header without retrying generation POST."""

import json
from types import SimpleNamespace

from rpg_vkr.visuals import client
from scripts import tunnel_health


def test_master_sends_one_post_then_authenticated_ngrok_job_get(qt_app):
    from rpg_vkr.narrative.cloud import CloudProfile
    from rpg_vkr.narrative.ollama import OllamaClient

    client = OllamaClient()
    endpoint = "https://test.ngrok-free.dev/api/v1/chat/completions"
    client.configure_cloud(
        CloudProfile("gateway", "deepseek/test", "tester-key", endpoint_url=endpoint)
    )
    requests = []
    signal = SimpleNamespace(connect=lambda callback: None)

    def send(request, body=None):
        requests.append((request, body))
        return SimpleNamespace(readyRead=signal, finished=signal)

    original = client.manager
    client.manager = SimpleNamespace(post=send, get=send)
    try:
        client._send("", "world_seed", {"messages": [], "options": {"num_predict": 65536}})
        client._gateway_job = (
            endpoint.removesuffix("/chat/completions") + "/jobs/" + "a" * 32,
            "tester-key",
        )
        client._poll_job()
        assert len(requests) == 2 and requests[0][1] is not None and requests[1][1] is None
        for request, _ in requests:
            assert bytes(request.rawHeader("ngrok-skip-browser-warning")) == b"1"
            assert bytes(request.rawHeader("Authorization")) == b"Bearer tester-key"
        assert json.loads(bytes(requests[0][1]))["max_tokens"] == 65536
    finally:
        client.timer.stop()
        client._reply = None
        client._gateway_job = None
        client.manager = original
        client.deleteLater()


def test_first_install_activation_uses_ngrok_header_without_owner_key(tmp_path, monkeypatch):
    from rpg_vkr.ui import tester_discovery as discovery

    bootstrap = tmp_path / "bootstrap.json"
    bootstrap.write_text(json.dumps({"code": "fake-one-use-code"}))
    monkeypatch.setattr(discovery, "resource_path", lambda _: bootstrap)
    monkeypatch.setattr(discovery, "load_secret", lambda _: "installation-secret")
    saved, results = {}, []
    monkeypatch.setattr(
        discovery, "save_secret", lambda path, value: saved.update({path.name: value})
    )
    monkeypatch.setattr(
        discovery,
        "fetch",
        lambda *a, **k: {"sequence": 1, "endpoint": "https://test.ngrok-free.dev/api/v1"},
    )

    class ImmediateThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(discovery.threading, "Thread", ImmediateThread)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return json.dumps({"token": "a" * 64}).encode()

    class Opener:
        def open(self, request, timeout):
            assert request.get_header("Ngrok-skip-browser-warning") == "1"
            assert not request.has_header("Authorization")
            assert json.loads(request.data)["code"] == "fake-one-use-code"
            return Response()

    monkeypatch.setattr(discovery.urllib.request, "build_opener", lambda *a: Opener())
    worker = SimpleNamespace(
        busy=False,
        window=SimpleNamespace(
            release_profile=SimpleNamespace(discovery="fake", verification_key="fake"),
            _saves=SimpleNamespace(directory=tmp_path / "saves"),
            _tester_token="",
        ),
        finished=SimpleNamespace(emit=results.append),
    )
    discovery.ConnectionWorker.start(worker)
    assert results[0]["token"] == "a" * 64 and saved == {"tester-access.bin": "a" * 64}


def test_image_async_uses_ngrok_header_and_slow_polling(monkeypatch):
    transport = client.ImagesTransport(
        gateway_base="https://test.ngrok-free.dev/api/v1", gateway_key="tester-key"
    )
    requests, sleeps = [], []
    job = "a" * 32

    class Response:
        def __init__(self, status, raw):
            self.status, self.raw = status, raw

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return self.raw

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            if len(requests) < 3:
                return Response(202, json.dumps({"job": job}).encode())
            return Response(200, b"image-result")

    transport.opener = Opener()
    monkeypatch.setattr(client.time, "sleep", lambda seconds: sleeps.append(seconds))
    raw = transport.read(transport.base + "/images", key="tester-key", payload={"prompt": "scene"})
    assert raw == b"image-result" and sleeps == [10]
    assert [r.get_method() for r in requests] == ["POST", "GET", "GET"]
    for request in requests:
        assert request.get_header("Ngrok-skip-browser-warning") == "1"
        assert request.get_header("Authorization") == "Bearer tester-key"


def test_health_uses_ngrok_browser_warning_bypass_header(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return json.dumps(tunnel_health.EXPECTED).encode()

    class Opener:
        def open(self, request, timeout):
            assert request.get_header("Ngrok-skip-browser-warning") == "1"
            assert not request.has_header("Authorization")
            return Response()

    monkeypatch.setattr(tunnel_health.urllib.request, "build_opener", lambda *a: Opener())
    assert tunnel_health.probe("https://test.ngrok-free.dev")["ok"]
