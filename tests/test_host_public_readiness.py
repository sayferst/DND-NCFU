"""Public readiness retries use GET only; no tunnel or external provider is started."""

import urllib.error

import pytest

from scripts import tester_host as host

ENDPOINT = "https://example.trycloudflare.com/api/v1"


@pytest.fixture
def clock(monkeypatch):
    current = [1.0]
    monkeypatch.setattr(host.time, "monotonic", lambda: current[0])
    monkeypatch.setattr(
        host.time, "sleep", lambda seconds: current.__setitem__(0, current[0] + seconds)
    )
    return current


def test_github_delay_and_tunnel_delay_retry_independently(monkeypatch, clock, capsys):
    fetched, healthy = [], []

    def fetch(url, key, *, previous):
        fetched.append((url, key, previous))
        if len(fetched) == 1:
            raise urllib.error.HTTPError(url, 404, "private detail", {}, None)
        return {"endpoint": ENDPOINT}

    def health(endpoint):
        healthy.append(endpoint)
        if len(healthy) == 1:
            raise urllib.error.HTTPError(endpoint, 502, "private detail", {}, None)

    monkeypatch.setattr(host, "fetch", fetch)
    monkeypatch.setattr(host, "check_health", health)
    assert host.wait_for_public_host(ENDPOINT, "public-key", 7, timeout=10, samples=1) == {
        "endpoint": ENDPOINT
    }
    assert fetched == [(host.DISCOVERY, "public-key", 7)] * 3
    assert healthy == [ENDPOINT] * 2
    assert "private detail" not in capsys.readouterr().out


@pytest.mark.parametrize("phase", ["document", "tunnel"])
def test_failure_names_actual_phase_without_raw_exception(monkeypatch, clock, capsys, phase):
    private = "sensitive-host-and-query"

    def failure(*args, **kwargs):
        raise urllib.error.HTTPError(private, 503, private, {}, None)

    monkeypatch.setattr(
        host, "fetch", failure if phase == "document" else lambda *a, **k: {"endpoint": ENDPOINT}
    )
    monkeypatch.setattr(host, "check_health", failure)
    with pytest.raises(ValueError) as error:
        host.wait_for_public_host(ENDPOINT, "key", 7, timeout=4)
    message = str(error.value)
    assert ("документ GitHub" if phase == "document" else "HTTPS-туннель Cloudflare") in message
    assert "HTTP 503" in message
    assert private not in message + capsys.readouterr().out


def test_stale_document_never_checks_or_accepts_old_tunnel(monkeypatch, clock):
    monkeypatch.setattr(host, "fetch", lambda *a, **k: {"endpoint": "https://old.example/api/v1"})
    monkeypatch.setattr(
        host, "check_health", lambda *a: pytest.fail("Stale address must not be used")
    )
    with pytest.raises(ValueError, match="документ GitHub"):
        host.wait_for_public_host(ENDPOINT, "key", 7, timeout=1)


def test_signature_failure_is_not_bypassed(monkeypatch, clock):
    def invalid(*args, **kwargs):
        raise ValueError("untrusted raw data")

    monkeypatch.setattr(host, "fetch", invalid)
    monkeypatch.setattr(host, "check_health", lambda *a: pytest.fail("Invalid signature"))
    with pytest.raises(ValueError, match="подпись") as error:
        host.wait_for_public_host(ENDPOINT, "key", 7, timeout=1)
    assert "untrusted raw data" not in str(error.value)
