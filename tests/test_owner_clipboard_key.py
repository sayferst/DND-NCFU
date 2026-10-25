"""Explicit clipboard import never echoes credentials or executes clipboard contents."""

import subprocess
from types import SimpleNamespace

import pytest

from scripts import tester_host


@pytest.mark.parametrize("account", ["admin", "tester"])
def test_account_key_replacement_does_not_touch_other_role(tmp_path, monkeypatch, capsys, account):
    calls = []
    monkeypatch.setattr("builtins.input", lambda _: "sk-fixture-only-key")
    monkeypatch.setattr(tester_host, "save_secret", lambda path, value: calls.append(path.name))
    tester_host.replace_owner_key(tmp_path, account=account)
    assert "account-" + account + "-key.bin" in calls
    other = "tester" if account == "admin" else "admin"
    assert "account-" + other + "-key.bin" not in calls
    assert ("routerai-key.bin" in calls) == (account == "admin")
    assert "sk-fixture" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "value",
    ["sk-fixture-only-key", "\ufeffsk-fixture-only-key\u200b", "\n sk-fixture-only-key\r\n"],
)
def test_clipboard_mode_saves_only_key_without_typing_or_echo(tmp_path, monkeypatch, capsys, value):
    calls = []
    monkeypatch.setattr("builtins.input", lambda _: "\x16")
    monkeypatch.setattr(tester_host, "clipboard_key_text", lambda: value)
    monkeypatch.setattr(
        tester_host, "save_secret", lambda path, secret: calls.append((path, secret))
    )
    tester_host.replace_owner_key(tmp_path, from_clipboard=True)
    assert calls == [(tmp_path / "routerai-key.bin", "sk-fixture-only-key")]
    assert "sk-fixture" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "value",
    [
        "",
        "\x16",
        "api sk-fixture-only-key",
        "Bearer sk-fixture-only-key",
        "sk-fixture\nsecond-key",
        "sk-fixture\u200bmiddle",
        '"sk-fixture-only-key"',
        "x" * 4097,
    ],
    ids=[
        "empty",
        "ctrl-v",
        "api-prefix",
        "bearer",
        "two-lines",
        "hidden-middle",
        "quotes",
        "oversized",
    ],
)
def test_bad_clipboard_or_hidden_input_never_overwrites_saved_key(
    tmp_path, monkeypatch, capsys, value
):
    monkeypatch.setattr("builtins.input", lambda _: value)
    monkeypatch.setattr(
        tester_host, "save_secret", lambda *_: pytest.fail("invalid input must preserve saved key")
    )
    with pytest.raises(ValueError, match="Ключ не сохранён"):
        tester_host.replace_owner_key(tmp_path)
    assert value not in capsys.readouterr().out if value else not capsys.readouterr().out


def test_clipboard_text_is_never_in_command_arguments_or_error_output(monkeypatch):
    value = 'sk-fixture-$(Write-Output "do-not-execute")'
    recorded = []

    def run(arguments, **kwargs):
        recorded.append(arguments)
        assert value not in " ".join(arguments)
        return SimpleNamespace(stdout=value.encode())

    monkeypatch.setattr(tester_host.subprocess, "run", run)
    assert tester_host.clipboard_key_text() == value
    assert len(recorded) == 1


@pytest.mark.parametrize(
    "error",
    [
        OSError("fixture-key-secret"),
        subprocess.TimeoutExpired("fixture-key-secret", 10),
        subprocess.CalledProcessError(1, "fixture-key-secret", output=b"fixture-key-secret"),
    ],
)
def test_clipboard_errors_never_disclose_private_subprocess_data(monkeypatch, error):
    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(tester_host.subprocess, "run", fail)
    with pytest.raises(ValueError) as captured:
        tester_host.clipboard_key_text()
    assert "fixture-key-secret" not in str(captured.value)


def test_cli_clipboard_flag_uses_existing_protected_owner_state(tmp_path, monkeypatch):
    import sys

    monkeypatch.setattr(
        tester_host, "os", SimpleNamespace(name="nt", environ={"LOCALAPPDATA": str(tmp_path)})
    )
    monkeypatch.setattr(
        tester_host, "Store", lambda *_a, **_k: pytest.fail("no quota database on key import")
    )
    seen = []
    monkeypatch.setattr(
        tester_host, "replace_owner_key", lambda path, **options: seen.append((path, options))
    )
    monkeypatch.setattr(sys, "argv", ["tester_host.py", "key", "--clipboard"])
    assert tester_host.main() == 0
    assert seen == [(tmp_path / "DND-NCFU-Host", {"from_clipboard": True})]


@pytest.mark.parametrize(
    "value", ["", "\x16", "sk-fixture\x00", "sk-fixture\u200b", "Bearer fixture", None]
)
def test_old_malformed_owner_key_cannot_be_sent_as_http_header(value):
    from server.gateway import Upstream

    with pytest.raises(ValueError, match="недопустимые символы"):
        Upstream(value)
