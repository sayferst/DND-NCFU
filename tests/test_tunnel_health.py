"""Read-only health routing and safe CF error details, no real network or credentials."""

import io
import json
import socket
import urllib.error
import urllib.request

import pytest

from scripts import tester_host as host
from scripts import tunnel_health as health


@pytest.mark.parametrize("code", ["1033", "1016", "1000"])
def test_cloudflare_error_body_reduced_to_fixed_codes(code):
    raw = ("<h1>Error " + code + "</h1> private-address sk-private-token").encode()
    result = health.classify_cloudflare(raw, {"cf-ray": "private-ray-id"})
    assert result == {"cloudflare_code": code, "cloudflare_header": True}
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize("body", [b"year 1033", b"Error 1999", b"x" * 16384 + b"Error 1033"])
def test_arbitrary_numbers_or_oversize_suffix_not_reported_as_cf_code(body):
    assert health.classify_cloudflare(body, {})["cloudflare_code"] == ""


@pytest.mark.parametrize("direct", [True, False])
def test_health_uses_get_without_auth_and_explicit_direct_proxy_handler(monkeypatch, direct):
    seen = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            assert size == 2049
            return json.dumps(health.EXPECTED).encode()

    class Opener:
        def open(self, request, timeout):
            assert request.get_method() == "GET" and request.data is None
            assert not request.has_header("Authorization")
            assert request.full_url == "https://test.example/api/v1/health"
            assert timeout == 10
            return Response()

    def build(*handlers):
        seen.extend(handlers)
        return Opener()

    monkeypatch.setattr(health.urllib.request, "build_opener", build)
    assert health.probe("https://test.example", direct=direct) == {"ok": True, "http_status": 200}
    proxies = [h for h in seen if isinstance(h, urllib.request.ProxyHandler)]
    assert bool(proxies) == direct
    if direct:
        assert proxies[0].proxies == {}


def test_http530_retains_cf_code_for_build_and_never_exposes_body(monkeypatch):
    class Opener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(
                "https://private-url.example",
                530,
                "private reason",
                {"cf-ray": "private-ray"},
                io.BytesIO(b"Error code: 1033 secret-payload"),
            )

    monkeypatch.setattr(health.urllib.request, "build_opener", lambda *a: Opener())
    result = health.result("https://test.example")
    assert result == {
        "ok": False,
        "http_status": 530,
        "cloudflare_code": "1033",
        "cloudflare_header": True,
    }
    with pytest.raises(urllib.error.HTTPError) as caught:
        health.probe("https://test.example")
    reason = host.public_check_reason(caught.value)
    assert "HTTP 530" in reason and "1033" in reason
    assert "private" not in reason and "secret-payload" not in reason


def test_dns_error_is_distinct_from_http530(monkeypatch):
    def fail(*a, **k):
        raise urllib.error.URLError(socket.gaierror("private hostname"))

    monkeypatch.setattr(health, "probe", fail)
    assert health.result("https://test.example") == {"ok": False, "error": "dns"}


@pytest.fixture
def diagnosis_env(tmp_path, monkeypatch):
    (tmp_path / "host-ready.json").write_text(
        json.dumps(
            {
                "pid": 123,
                "discovery": host.DISCOVERY,
                "verification_key": "public-key",
                "sequence": 7,
            }
        )
    )
    monkeypatch.setattr(host, "fetch", lambda *a, **k: {"endpoint": "https://test.example/api/v1"})
    monkeypatch.setattr(host, "host_process_alive", lambda pid: True)
    monkeypatch.setattr(host.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        host.urllib.request, "getproxies", lambda: {"https": "private-proxy-with-password"}
    )
    monkeypatch.setattr(host, "load_secret", lambda *a: pytest.fail("No DPAPI read permitted"))
    return tmp_path


def test_repeated_direct_success_vs_system_proxy_failure_is_explicit(diagnosis_env, monkeypatch):
    calls = []

    def result(endpoint, *, direct):
        calls.append(direct)
        return {"ok": True, "http_status": 200} if direct else {"ok": False, "http_status": 530}

    monkeypatch.setattr(health, "result", result)
    value = host.diagnose_tunnel(diagnosis_env)
    assert calls == [False, True] * 3
    assert value["diagnosis"] == "system_proxy_route" and not value["ok"]
    assert not value["grant_created"] and not value["secrets_read"]
    assert "private-proxy" not in json.dumps(value)


@pytest.mark.parametrize(
    "code,diagnosis", [("1033", "connector_lost_1033"), ("1016", "origin_dns_1016")]
)
def test_cf_errors_on_both_routes_are_not_called_proxy_failures(
    diagnosis_env, monkeypatch, code, diagnosis
):
    monkeypatch.setattr(
        health, "result", lambda *a, **k: {"ok": False, "http_status": 530, "cloudflare_code": code}
    )
    assert host.diagnose_tunnel(diagnosis_env)["diagnosis"] == diagnosis


def test_signature_failure_prevents_all_public_health_requests(diagnosis_env, monkeypatch):
    def fail(*a, **k):
        raise ValueError("untrusted private content")

    monkeypatch.setattr(host, "fetch", fail)
    monkeypatch.setattr(health, "result", lambda *a, **k: pytest.fail("Unverified endpoint"))
    value = host.diagnose_tunnel(diagnosis_env)
    assert not value["discovery_ok"] and "private" not in json.dumps(value)


def test_diagnose_tunnel_cli_never_opens_grant_database_or_reads_key(tmp_path, monkeypatch, capsys):
    import sys
    from types import SimpleNamespace

    monkeypatch.setattr(
        host, "os", SimpleNamespace(name="nt", environ={"LOCALAPPDATA": str(tmp_path)})
    )
    monkeypatch.setattr(host, "Store", lambda *a, **k: pytest.fail("No grant database"))
    monkeypatch.setattr(host, "load_secret", lambda *a: pytest.fail("No owner key"))
    monkeypatch.setattr(host, "diagnose_tunnel", lambda root: {"ok": False, "paid_requests": 0})
    monkeypatch.setattr(sys, "argv", ["tester_host.py", "diagnose-tunnel"])
    assert host.main() == 2
    assert json.loads(capsys.readouterr().out) == {"ok": False, "paid_requests": 0}
