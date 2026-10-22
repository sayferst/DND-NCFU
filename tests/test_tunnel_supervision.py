"""Connector loss/recovery with fake child process, clock and public health; no paid calls."""

import io
import json
import urllib.error
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import tester_host as host
from scripts import tunnel_dns
from scripts.tunnel_supervision import PublicMonitor, RestartBudget, RestartTunnel, write_ready

ENDPOINT = "https://test.trycloudflare.com"


def lost():
    error = urllib.error.HTTPError(ENDPOINT, 530, "private detail", {}, None)
    error.gateway_details = {"cloudflare_code": "1033"}
    raise error


def test_loss_withdraws_readiness_and_three_failures_request_restart(tmp_path):
    ready = {"pid": 1, "sequence": 7}
    write_ready(tmp_path, ready)
    monitor = PublicMonitor(tmp_path, ready)
    assert "1033" in monitor.check(lost, host.public_check_reason)
    assert not (tmp_path / "host-ready.json").exists()
    monitor.check(lost, host.public_check_reason)
    with pytest.raises(RestartTunnel, match="1033") as error:
        monitor.check(lost, host.public_check_reason)
    assert "private detail" not in str(error.value)


def test_recovery_needs_three_good_checks_and_preserves_ready_fields(tmp_path):
    ready = {"pid": 1, "sequence": 7}
    monitor = PublicMonitor(tmp_path, ready)
    monitor.check(lost, host.public_check_reason)
    for _ in range(2):
        assert monitor.check(lambda: None, host.public_check_reason)
        assert not (tmp_path / "host-ready.json").exists()
    assert monitor.check(lambda: None, host.public_check_reason) == ""
    assert json.loads((tmp_path / "host-ready.json").read_text()) == ready
    assert len(list(tmp_path.iterdir())) == 1


def test_retry_budget_is_bounded_and_expires_after_one_hour():
    budget = RestartBudget()
    assert [budget.delay(now) for now in (0, 10, 20)] == [5, 15, 30]
    with pytest.raises(ValueError, match="три восстановления"):
        budget.delay(30)
    assert budget.delay(3621) == 5


def test_initial_gate_requires_consecutive_success_not_one_registration(monkeypatch):
    clock = [0]
    monkeypatch.setattr(host.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        host.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    monkeypatch.setattr(host, "fetch", lambda *a, **k: {"endpoint": ENDPOINT + "/api/v1"})
    calls = []

    def probe(endpoint):
        calls.append(endpoint)
        if len(calls) == 2:
            lost()

    monkeypatch.setattr(host, "check_health", probe)
    host.wait_for_public_host(ENDPOINT, "public", 7, timeout=60)
    assert len(calls) == 5 and clock[0] >= 15


def test_dead_child_cannot_pass_initial_public_gate(monkeypatch):
    monkeypatch.setattr(host, "fetch", lambda *a, **k: pytest.fail("Dead child"))
    with pytest.raises(RestartTunnel, match="cloudflared завершился"):
        host.wait_for_public_host(ENDPOINT, "public", 7, process=SimpleNamespace(poll=lambda: 1))


def test_session_lost_after_readiness_is_cleaned_up_before_restart(tmp_path, monkeypatch):
    clock, probes, published = [0], [], []
    monkeypatch.setattr(host.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        host.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )

    class Process:
        def __init__(self):
            self.returncode = None
            self.stdout = io.StringIO(ENDPOINT + "\nRegistered tunnel connection connIndex=0\n")
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def wait(self, timeout):
            return self.returncode

    process = Process()
    monkeypatch.setattr(host.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(host, "publish", lambda value: published.append(value))
    monkeypatch.setattr(host, "fetch", lambda *a, **k: {"endpoint": ENDPOINT + "/api/v1"})

    def health(endpoint):
        probes.append(endpoint)
        if len(probes) > 3:
            if len(probes) == 4:
                assert (tmp_path / "host-ready.json").exists()
            else:
                assert not (tmp_path / "host-ready.json").exists()
            lost()

    monkeypatch.setattr(host, "check_health", health)
    with pytest.raises(RestartTunnel, match="1033"):
        host.run_tunnel_session(
            tmp_path,
            SimpleNamespace(server_port=1234),
            Ed25519PrivateKey.generate(),
            "cloudflared",
            ("198.41.192.167:7844",),
            "http2",
        )
    assert process.terminated and not (tmp_path / "host-ready.json").exists()
    assert len(published) == 1 and len(probes) == 6


def test_recreating_connector_reuses_gateway_and_store_and_ctrl_c_cleans_up(tmp_path, monkeypatch):
    servers, sessions, sleeps = [], [], []
    store = object()
    monkeypatch.setattr(host, "cloudflared_path", lambda: "cloudflared")
    monkeypatch.setattr(host, "private_key", lambda root: Ed25519PrivateKey.generate())
    monkeypatch.setattr(host, "load_secret", lambda path: "fake-api-key")
    monkeypatch.setattr(host, "check_provider", lambda gateway: None)
    monkeypatch.setattr(tunnel_dns, "resolve_tunnel_edges", lambda: ("198.41.192.167:7844",))
    monkeypatch.setattr(tunnel_dns, "reachable_edges", lambda edges: edges)
    monkeypatch.setattr(host.time, "sleep", lambda seconds: sleeps.append(seconds))

    class Server:
        server_port = 1234

        def __init__(self, address, gateway):
            self.gateway = gateway
            self.closed = False
            servers.append(self)

        def serve_forever(self):
            pass

        def shutdown(self):
            self.closed = True

        def server_close(self):
            pass

    def session(root, server, private, tunnel, edges, protocol):
        assert server.gateway.store is store
        sessions.append((server, protocol))
        if len(sessions) == 1:
            raise RestartTunnel("HTTP530 Cloudflare1033")
        (root / "host-ready.json").write_text("{}")
        raise KeyboardInterrupt

    monkeypatch.setattr(host, "Server", Server)
    monkeypatch.setattr(host, "run_tunnel_session", session)
    with pytest.raises(KeyboardInterrupt):
        host.host(tmp_path, store)
    assert len(servers) == 1 and servers[0].closed
    assert [protocol for _, protocol in sessions] == ["http2", "quic"]
    assert sessions[0][0] is sessions[1][0] and sleeps == [5]
    assert not (tmp_path / "host-ready.json").exists()
