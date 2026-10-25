"""Account isolation, persisted throttling and lifetime budgets with synthetic credentials."""

from contextlib import closing

import pytest
from test_gateway import FakeUpstream

from server.accounts import configure, login
from server.gateway import Denied, Gateway, Store


def accounts(tmp_path):
    store = Store(tmp_path / "access.sqlite3", 600_000_000)
    configure(store, "admin", "synthetic-admin-password")
    configure(store, "tester", "synthetic-tester-password")
    return store


def test_account_host_rejects_legacy_tokens_without_erasing_history(tmp_path):
    from scripts.tester_host import AccountStore

    store = accounts(tmp_path)
    old = store.issue("legacy", budget=100_000_000)
    strict = AccountStore(store.path, 600_000_000)
    with pytest.raises(Denied, match="account_login_required"):
        strict.identity(old)
    token = login(strict, "tester", "synthetic-tester-password")["token"]
    assert strict.identity(token)["id"] == "account_tester"
    assert "legacy" in {row["id"] for row in strict.summary()}


def test_login_budget_persistence_revocation_and_secrets(tmp_path):
    store = accounts(tmp_path)
    admin = login(store, "admin", "synthetic-admin-password")
    tester = login(store, "tester", "synthetic-tester-password")
    assert store.allowance(admin["token"])["data"]["limit_remaining"] == 500
    assert store.allowance(tester["token"])["data"]["limit_remaining"] == 100
    user = store.reserve(tester["token"], "request-one" * 3, 99_000_000, "director")
    store.settle(user, "request-one" * 3, 99_000_000, succeeded=True)
    configure(store, "tester", "replacement-password")
    with pytest.raises(Denied):
        store.identity(tester["token"])
    other = login(store, "tester", "replacement-password")["token"]
    assert store.allowance(other)["data"]["limit_remaining"] == 1
    with pytest.raises(Denied, match="budget_exhausted"):
        store.reserve(other, "second-request" * 3, 2_000_000, "director")
    assert store.allowance(admin["token"])["data"]["limit_remaining"] == 500
    raw = store.path.read_bytes()
    assert b"synthetic-admin-password" not in raw and admin["token"].encode() not in raw
    store.revoke("account_admin")
    with pytest.raises(Denied):
        store.identity(admin["token"])


def test_failed_login_throttle_survives_reopen(tmp_path):
    store = accounts(tmp_path)
    for _ in range(5):
        with pytest.raises(Denied, match="login_failed"):
            login(store, "tester", "wrong")
    reopened = Store(store.path, 600_000_000)
    with pytest.raises(Denied, match="login_throttled"):
        login(reopened, "tester", "synthetic-tester-password")
    with closing(store.connect()) as db, db:
        db.execute("UPDATE accounts SET blocked=0 WHERE name='tester'")
    assert login(store, "tester", "synthetic-tester-password")["account"] == "tester"


def test_account_provider_selection_has_no_fallback(tmp_path):
    store = accounts(tmp_path)
    admin, tester, default = FakeUpstream(), FakeUpstream(), FakeUpstream()
    gateway = Gateway(store, default)
    gateway.account_upstreams = {"account_admin": admin, "account_tester": tester}
    for name, provider in (("admin", admin), ("tester", tester)):
        token = login(store, name, "synthetic-" + name + "-password")["token"]
        identity = name * 8
        user = store.reserve(token, identity, 100_000, "director")
        gateway.execute("chat/completions", {}, user, identity)
        assert len(provider.posts) == 1
    assert not default.posts
    gateway.account_upstreams = {}
    token = login(store, "tester", "synthetic-tester-password")["token"]
    user = store.reserve(token, "missing-provider-id", 100_000, "director")
    with pytest.raises(Denied, match="account_provider_unavailable"):
        gateway.execute("chat/completions", {}, user, "missing-provider-id")


def test_real_http_login_and_pairing_dialog(qt_app, tmp_path):
    from test_gateway import running
    from test_local_narrator import wait_for

    from rpg_vkr.deployment import ReleaseProfile
    from rpg_vkr.storage.slots import SaveSlots
    from rpg_vkr.ui.account_login import LoginDialog, check_connection
    from rpg_vkr.ui.main_window import MainWindow

    with running(tmp_path) as (base, _, store, upstream, gateway):
        store.global_budget = 600_000_000
        configure(store, "tester", "synthetic-tester-password")
        gateway.account_upstreams = {"account_tester": upstream}
        window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
        window.release_profile = ReleaseProfile(mode="tester", gateway=base, account_login=True)
        window._tester_token = ""
        dialog = LoginDialog(window)
        try:
            dialog.show()
            dialog.username.setText("tester")
            dialog.password.setText("wrong")
            dialog.submit.click()
            wait_for(qt_app, lambda: dialog.submit.isEnabled())
            assert not window._tester_token
            dialog.password.setText("synthetic-tester-password")
            dialog.submit.click()
            wait_for(qt_app, lambda: bool(window._tester_token))
            assert store.identity(window._tester_token)["id"] == "account_tester"
            assert dialog.password.text() == ""
            check_connection(window)
            wait_for(qt_app, lambda: not window.account_connection_check.busy)
            assert "Сопряжение установлено" in window.statusBar().currentMessage()
            assert not upstream.posts
        finally:
            dialog.close()
            window.close()


def test_account_build_greets_with_login_and_replaces_activation(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QPushButton

    from rpg_vkr.deployment import ReleaseProfile
    from rpg_vkr.storage.slots import SaveSlots
    from rpg_vkr.ui import account_login, tester_connection
    from rpg_vkr.ui.main_window import MainWindow

    calls = []
    profile = ReleaseProfile(mode="tester", gateway="https://example.org", account_login=True)
    monkeypatch.setattr(tester_connection, "load_release_profile", lambda: profile)
    monkeypatch.setattr(tester_connection, "load_secret", lambda path: "old-installation-token")
    monkeypatch.setattr(account_login, "show_login", lambda window: calls.append(window))
    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    try:
        qt_app.processEvents()
        assert calls == [window] and window._tester_token == ""
        labels = [button.text() for button in window.findChildren(QPushButton)]
        assert "Проверить сопряжение" in labels
        assert not any(label.startswith("Активировать") for label in labels)
        window._account_name = "tester"
        assert window.developer_console.enter() is False
    finally:
        window.close()
