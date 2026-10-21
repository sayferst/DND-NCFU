"""Tester delivery: signed discovery, one-install activation, async jobs and quotas.

All servers are loopback fakes. No paid API, tunnel or GitHub publication occurs.
"""

import base64
import json
import secrets
import threading
import time
import urllib.error
import urllib.request

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from rpg_vkr.discovery import discovery_url, public_endpoint, verify
from scripts.tester_host import signed_manifest
from server.gateway import Denied, Store
from tests.test_gateway import body, request, running


def signing():
    key = Ed25519PrivateKey.generate()
    return key, base64.b64encode(key.public_key().public_bytes_raw()).decode()


def test_signature_tamper_replay_expiry_wrong_key_and_private_endpoint():
    key, public = signing()
    value = signed_manifest(key, "https://test.trycloudflare.com", 7, now=1000)
    raw = json.dumps(value).encode()
    assert verify(raw, public, now=1001)["endpoint"].endswith("/api/v1")
    for damaged in (
        value | {"endpoint": "https://thief.example.org"},
        value | {"sequence": 9},
        value | {"expires": 9999999},
    ):
        with pytest.raises(ValueError):
            verify(json.dumps(damaged).encode(), public, now=1001)
    for options in ({"previous": 8, "now": 1001}, {"now": 999}, {"now": 4000000}):
        # Future issuance allows 300 seconds of clock skew; 999 is legitimate.
        if options["now"] == 999:
            options["now"] = 600
        with pytest.raises(ValueError):
            verify(raw, public, **options)
    with pytest.raises(ValueError):
        verify(raw, signing()[1], now=1001)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:42",
        "https://127.0.0.1",
        "https://192.168.1.1",
        "https://localhost",
        "https://owner.local",
        "https://u:p@host.example",
        "https://host.example?key=secret",
        "https://host.example:8443",
    ],
)
def test_discovery_rejects_nonpublic_targets(endpoint):
    with pytest.raises(ValueError):
        public_endpoint(endpoint)


def test_discovery_source_is_fixed_to_public_owner_repository():
    assert discovery_url(
        "https://raw.githubusercontent.com/sayferst/DND-NCFU/tester-host-address/endpoint.json"
    )
    for url in (
        "http://raw.githubusercontent.com/sayferst/DND-NCFU/x/endpoint.json",
        "https://raw.githubusercontent.com/thief/DND-NCFU/x/endpoint.json",
        "https://raw.githubusercontent.com/sayferst/DND-NCFU/x/endpoint.json?token=secret",
    ):
        with pytest.raises(ValueError):
            discovery_url(url)


def test_one_install_activation_recovery_revocation_expiry_extension(tmp_path):
    clock = [1000]
    store = Store(tmp_path / "db", clock=lambda: clock[0])
    code = store.bootstrap("one", days=30, budget=100_000_000, requests=10000, worlds=100)
    install = secrets.token_urlsafe(32)
    with pytest.raises(Denied):
        store.identity(code)
    token = store.activate(code, install)["token"]
    assert store.activate(code, install)["token"] == token
    assert Store(store.path, clock=lambda: clock[0]).identity(token)["id"] == "one"
    with pytest.raises(Denied, match="already_activated"):
        store.activate(code, secrets.token_urlsafe(32))
    store.reserve(token, "q" * 20, 700, "world_seed")
    store.settle("one", "q" * 20, 100, succeeded=True)
    expiry = store.summary()[0]["expires"]
    store.extend("one", 30)
    assert store.summary()[0]["expires"] == expiry + 30 * 86400
    assert store.summary()[0]["committed"] == 100
    clock[0] += 31 * 86400
    assert store.identity(token)["id"] == "one"
    store.revoke("one")
    with pytest.raises(Denied):
        store.activate(code, install)
    with pytest.raises(Denied):
        store.identity(token)
    assert (
        code.encode() not in store.path.read_bytes()
        and token.encode() not in store.path.read_bytes()
    )


def async_request(base, token, value, request_id="c" * 32):
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(value).encode(),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "X-Request-ID": request_id,
            "X-DND-Stage": "world_seed",
            "Prefer": "respond-async",
        },
    )
    with urllib.request.urlopen(req, timeout=3) as reply:
        return reply.status, json.load(reply)


def test_async_real_http_returns_before_upstream_and_polls_without_rebilling(tmp_path):
    with running(tmp_path) as (base, token, store, upstream, gateway):
        entered, release = threading.Event(), threading.Event()
        original = upstream.request

        def slow(route, value=None):
            if value is not None:
                entered.set()
                assert release.wait(5)
            return original(route, value)

        upstream.request = slow
        status, result = async_request(base, token, body())
        assert status == 202 and entered.wait(2)
        try:
            for _ in range(5):
                assert request(base, token, "jobs/" + result["job"])[0] == 202
            assert async_request(base, token, body()) == (202, result)
            other = store.issue("other")
            assert request(base, other, "jobs/" + result["job"])[0] == 404
            assert not upstream.posts
        finally:
            release.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status, value = request(base, token, "jobs/" + result["job"])
            if status == 200:
                break
            time.sleep(0.01)
        assert status == 200 and value["choices"]
        assert len(upstream.posts) == 1 and store.summary()[0]["calls"] == 1
        assert async_request(base, token, body()) == (202, result)
        store.revoke("one")
        assert request(base, token, "jobs/" + result["job"])[0] == 401


def test_public_health_and_activation_never_call_paid_upstream(tmp_path):
    with running(tmp_path) as (base, _, store, upstream, _):
        with urllib.request.urlopen(base + "/health", timeout=3) as reply:
            assert json.load(reply)["async_jobs"] is True
        code = store.bootstrap("auto", days=30, budget=100_000_000)
        req = urllib.request.Request(
            base + "/activate",
            data=json.dumps({"code": code, "installation": secrets.token_urlsafe(32)}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as reply:
            token = json.load(reply)["token"]
        assert store.identity(token)["id"] == "auto" and not upstream.posts


def test_qt_automatic_activation_is_nonblocking_and_recovers_install_secret(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from rpg_vkr.deployment import ReleaseProfile
    from rpg_vkr.storage.slots import SaveSlots
    from rpg_vkr.ui import tester_connection, tester_discovery
    from rpg_vkr.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    with running(tmp_path) as (base, _, store, upstream, _):
        code = store.bootstrap("qt", days=30, budget=100_000_000)
        bootstrap = tmp_path / "bootstrap.json"
        bootstrap.write_text(json.dumps({"code": code}))
        key, public = signing()
        profile = ReleaseProfile(
            "tester",
            discovery="https://raw.githubusercontent.com/sayferst/DND-NCFU/tester-host-address/endpoint.json",
            verification_key=public,
        )
        monkeypatch.setattr(tester_connection, "load_release_profile", lambda: profile)
        monkeypatch.setattr(
            tester_discovery, "fetch", lambda *a, **k: {"endpoint": base, "sequence": 7}
        )
        monkeypatch.setattr(tester_discovery, "resource_path", lambda _: bootstrap)
        secrets_store = {}
        monkeypatch.setattr(
            tester_discovery, "load_secret", lambda p: secrets_store.get(p.name, "")
        )
        monkeypatch.setattr(
            tester_discovery, "save_secret", lambda p, v: secrets_store.update({p.name: v})
        )
        window = MainWindow(saves=SaveSlots(tmp_path / "qt/saves"))
        try:
            assert not getattr(window, "_tester_endpoint", "")
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and not getattr(window, "_tester_endpoint", ""):
                app.processEvents()
                time.sleep(0.01)
            assert window._tester_endpoint == base
            assert store.identity(window._tester_token)["id"] == "qt"
            assert secrets_store["tester-installation.bin"] and secrets_store["tester-access.bin"]
            assert window.ollama.cloud.provider == "gateway"
            assert not upstream.posts
        finally:
            window.tester_connection_worker.timer.stop()
            window.close()
            window.deleteLater()
            app.processEvents()


def test_publication_branch_contains_only_signed_address_and_updates_fast_forward(
    tmp_path, monkeypatch
):
    import subprocess

    from scripts import tester_host

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
    actual = tester_host.git

    def local_git(*args, **kwargs):
        if args[:3] == ("remote", "get-url", "origin"):
            return "https://github.com/sayferst/DND-NCFU.git"
        if args[:3] == ("remote", "add", "origin"):
            args = (*args[:3], str(remote))
        return actual(*args, **kwargs)

    monkeypatch.setattr(tester_host, "git", local_git)
    key, public = signing()
    for sequence in (1, 2):
        value = signed_manifest(key, "https://unit.trycloudflare.com", sequence)
        tester_host.publish(value)
        names = actual("ls-tree", "--name-only", tester_host.BRANCH, cwd=remote)
        assert names == "endpoint.json"
        raw = actual("show", tester_host.BRANCH + ":endpoint.json", cwd=remote).encode()
        assert verify(raw, public)["sequence"] == sequence
    assert actual("rev-list", "--count", tester_host.BRANCH, cwd=remote) == "2"


def test_msi_cloudflared_path_with_spaces_without_terminal_path_refresh(tmp_path, monkeypatch):
    from scripts import tester_host

    install = tmp_path / "Program Files" / "cloudflared" / "cloudflared.exe"
    install.parent.mkdir(parents=True)
    install.write_bytes(b"fixture-not-an-executable")
    monkeypatch.setattr(tester_host.shutil, "which", lambda _: None)
    monkeypatch.setenv("ProgramFiles", str(install.parent.parent))
    assert tester_host.cloudflared_path() == str(install)


def test_job_eviction_cannot_make_old_request_pay_again(tmp_path):
    with running(tmp_path) as (_, token, store, upstream, gateway):
        jobs = __import__("server.jobs", fromlist=["Jobs"]).Jobs(gateway, capacity=1)
        first = jobs.submit("chat/completions", token, body(), "a" * 32, "world_seed")[1]["job"]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and jobs.get(token, first)[0] == 202:
            time.sleep(0.01)
        second = jobs.submit("chat/completions", token, body(), "b" * 32, "world_seed")[1]["job"]
        with pytest.raises(Denied, match="job_unavailable"):
            jobs.get(token, first)
        with pytest.raises(Denied, match="request_already_received"):
            jobs.submit("chat/completions", token, body(), "a" * 32, "world_seed")
        while time.monotonic() < deadline and jobs.get(token, second)[0] == 202:
            time.sleep(0.01)
        assert len(upstream.posts) == 2 and store.summary()[0]["calls"] == 2


def test_async_poll_cancel_does_not_start_another_paid_request(qt_app, tmp_path):
    from test_local_narrator import wait_for

    from rpg_vkr.narrative.cloud import CloudProfile
    from rpg_vkr.narrative.ollama import OllamaClient

    with running(tmp_path) as (base, token, _, upstream, _):
        entered, release = threading.Event(), threading.Event()
        original = upstream.request

        def slow(route, value=None):
            if value:
                entered.set()
                release.wait(3)
            return original(route, value)

        upstream.request = slow
        client = OllamaClient()
        client.configure_cloud(
            CloudProfile(
                "gateway",
                "~deepseek/deepseek-v4-flash-latest",
                token,
                endpoint_url=base + "/chat/completions",
            )
        )
        try:
            client._send(
                "",
                "world_seed",
                {
                    "messages": [{"role": "user", "content": "world"}],
                    "options": {"num_predict": 65536},
                },
            )
            wait_for(qt_app, lambda: client._gateway_job is not None)
            assert entered.is_set() and client.busy
            client.cancel()
            assert not client.busy and not client._poll_timer.isActive()
        finally:
            release.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not upstream.posts:
            qt_app.processEvents()
            time.sleep(0.01)
        assert len(upstream.posts) == 1
        client.deleteLater()
        qt_app.processEvents()


def test_owner_preflight_checks_metadata_only_and_refuses_missing_models(tmp_path):
    from scripts.tester_host import check_provider
    from server.gateway import Gateway
    from tests.test_gateway import FakeUpstream

    store = Store(tmp_path / "db")
    upstream = FakeUpstream()
    original = upstream.request

    def metadata(route, value=None):
        if route == "key":
            return {
                "data": {
                    "disabled": False,
                    "limit": "100",
                    "usage_monthly": "0",
                    "limit_remaining": "100",
                    "limit_reset": "monthly",
                }
            }
        return original(route, value)

    upstream.request = metadata
    gateway = Gateway(store, upstream)
    check_provider(gateway)
    assert not upstream.posts and not store.summary()
    upstream.request = lambda route, value=None: (
        metadata(route, value) if route == "key" else {"data": []}
    )
    gateway.cache = None
    # Use fresh Gateway to avoid a still-valid cached model catalog.
    with pytest.raises(ValueError, match="отсутствуют модели") as failure:
        check_provider(Gateway(store, upstream))
    assert "~deepseek/deepseek-v4-flash-latest" in str(failure.value)
    assert not upstream.posts


def test_public_build_profile_and_bootstrap_are_separate_and_owner_keys_ignored(
    tmp_path, monkeypatch
):
    from scripts.release_tools import prepare_bootstrap, prepare_release_profile

    _, public = signing()
    monkeypatch.setenv("DND_BUILD_PROFILE", "tester")
    monkeypatch.setenv(
        "DND_DISCOVERY_URL",
        "https://raw.githubusercontent.com/sayferst/DND-NCFU/tester-host-address/endpoint.json",
    )
    monkeypatch.setenv("DND_DISCOVERY_KEY", public)
    monkeypatch.setenv("DND_ROUTERAI_KEY", "owner-key-must-not-appear")
    monkeypatch.setenv("DND_TESTER_TOKEN", "access-token-must-not-appear")
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"code": "C" * 43}))
    monkeypatch.setenv("DND_BOOTSTRAP_FILE", str(source))
    profile = prepare_release_profile(tmp_path / "release-profile.json")
    personal = prepare_bootstrap(tmp_path / "tester-bootstrap.json")
    assert json.loads(personal.read_text()) == {"code": "C" * 43}
    assert json.loads(profile.read_text())["verification_key"] == public
    assert "C" * 43 not in profile.read_text()
    assert "owner-key" not in profile.read_text() + personal.read_text()
    assert "access-token" not in profile.read_text() + personal.read_text()
    monkeypatch.setenv("DND_BUILD_PROFILE", "developer")
    with pytest.raises(ValueError):
        prepare_bootstrap(tmp_path / "bad.json")


def test_catalog_alias_matches_owner_public_catalog(tmp_path):
    from rpg_vkr.deployment import ReleaseProfile
    from server.gateway import TEXT_MODEL, Gateway
    from tests.test_gateway import FakeUpstream

    canonical = "~deepseek/deepseek-v4-flash-latest"
    assert TEXT_MODEL == canonical
    assert ReleaseProfile(mode="tester").text_model == canonical
    upstream = FakeUpstream()
    gateway = Gateway(Store(tmp_path / "alias.sqlite3"), upstream)
    gateway.validate(
        "chat/completions",
        {
            "model": canonical,
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 65536,
            "stream": False,
        },
        "world_seed",
    )
    assert not upstream.posts
