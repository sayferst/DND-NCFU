"""Shared installer requires a separately supplied code, not embedded owner credentials."""

from types import SimpleNamespace

import pytest

from rpg_vkr.ui import tester_connection as connection


@pytest.mark.parametrize("code,accepted", [("A" * 43, True), ("wrong", False)])
def test_signed_shared_profile_requires_explicit_bootstrap_code(monkeypatch, code, accepted):
    calls, messages = [], []
    window = SimpleNamespace(
        release_profile=SimpleNamespace(discovery="signed-discovery"),
        _tester_token="",
        tester_connection_worker=SimpleNamespace(start=lambda: calls.append(True)),
        statusBar=lambda: SimpleNamespace(showMessage=messages.append),
    )
    monkeypatch.setattr(connection.QInputDialog, "getText", lambda *a: (code, True))
    monkeypatch.setattr(connection, "windows_credentials_available", lambda: False)
    connection.activate(window)
    assert bool(calls) == accepted
    if accepted:
        assert window._tester_bootstrap == code
    else:
        assert messages and not hasattr(window, "_tester_bootstrap")
