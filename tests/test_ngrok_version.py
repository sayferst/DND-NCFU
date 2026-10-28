"""Old winget agent fails before tunnel retries; owner updates a private copy."""

import io
import queue
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import ngrok_host as ngrok
from scripts.tunnel_supervision import RestartTunnel


@pytest.mark.parametrize("found", ["3.3.1", "3.39.11"])
def test_old_agent_rejected_without_tunnel_or_retry(tmp_path, monkeypatch, found):
    monkeypatch.setattr(
        ngrok.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="ngrok version " + found + "\n"),
    )
    monkeypatch.setattr(ngrok.subprocess, "Popen", lambda *a, **k: pytest.fail("No tunnel"))
    with pytest.raises(ValueError, match="update-ngrok") as error:
        with ngrok.running(
            tmp_path, "agent.exe", 1234, "test.ngrok-free.dev", "fake-token-1234567890"
        ):
            pytest.fail("Must stop before tunnel")
    assert not isinstance(error.value, RestartTunnel)
    assert found in str(error.value) and not list(tmp_path.iterdir())


@pytest.mark.parametrize("found", ["3.39.12", "3.40.0", "4.0.0"])
def test_supported_version_parses_only_numeric_version(monkeypatch, found):
    monkeypatch.setattr(
        ngrok.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="ngrok version " + found + "\n"),
    )
    assert ngrok.require_supported("agent.exe") == tuple(map(int, found.split(".")))


def test_unknown_version_does_not_echo_raw_agent_output(monkeypatch):
    monkeypatch.setattr(
        ngrok.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="private-path private-token"),
    )
    with pytest.raises(ValueError, match="update-ngrok") as error:
        ngrok.require_supported("agent.exe")
    assert "private" not in str(error.value)


def test_update_uses_portable_copy_and_no_owner_secrets(tmp_path, monkeypatch, capsys):
    installed = tmp_path / "winget" / "ngrok.exe"
    installed.parent.mkdir()
    installed.write_bytes(b"installed-old-binary")
    root = tmp_path / "host"
    root.mkdir()
    (root / "ngrok-token.bin").write_bytes(b"protected-token")
    (root / "tunnel.json").write_text('{"provider":"ngrok","domain":"test.ngrok-free.dev"}')
    monkeypatch.setattr(ngrok, "executable", lambda: str(installed))
    monkeypatch.setenv("NGROK_AUTHTOKEN", "private-environment-token")
    monkeypatch.setenv("NGROK_API_KEY", "private-api-key")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert Path(args[0]) != installed
        if args[1] == "update":
            assert "NGROK_AUTHTOKEN" not in kwargs["env"] and "NGROK_API_KEY" not in kwargs["env"]
            assert "private" not in Path(args[-1]).read_text()
            Path(args[0]).write_bytes(b"updated-signed-binary")
            return SimpleNamespace(returncode=0, stdout="do not echo private-token")
        return SimpleNamespace(returncode=0, stdout="ngrok version 3.39.12\n")

    from scripts import ngrok_download

    monkeypatch.setattr(
        ngrok_download, "download_agent", lambda p: p.write_bytes(b"updated-signed-binary")
    )
    monkeypatch.setattr(ngrok.subprocess, "run", run)
    ngrok.update_agent(root)
    assert [args[1] for args in calls] == ["version"]
    assert installed.read_bytes() == b"installed-old-binary"
    assert (root / "ngrok-agent/ngrok.exe").read_bytes() == b"updated-signed-binary"
    assert (root / "ngrok-token.bin").read_bytes() == b"protected-token"
    assert not list(root.glob("*.yml")) and "private" not in capsys.readouterr().out


def test_project_agent_preferred_over_stale_winget_alias(tmp_path, monkeypatch):
    installed = tmp_path / "ngrok.exe"
    installed.write_bytes(b"old")
    managed = tmp_path / "DND-NCFU-Host/ngrok-agent/ngrok.exe"
    managed.parent.mkdir(parents=True)
    managed.write_bytes(b"new")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(ngrok.shutil, "which", lambda _: str(installed))
    assert ngrok.executable() == str(managed.resolve())


@pytest.mark.parametrize("installed", [True, False])
def test_direct_download_replaces_missing_or_existing_agent_without_self_update(
    tmp_path, monkeypatch, installed
):
    from scripts import ngrok_download

    target = tmp_path / "ngrok-agent/ngrok.exe"
    target.parent.mkdir()
    backup = target.parent / ".ngrok.exe.old"
    backup.write_bytes(b"previous-user-backup")
    source = tmp_path / "winget.exe"
    source.write_bytes(b"old-bootstrap")
    if installed:
        target.write_bytes(b"working-installed-agent")
    monkeypatch.setattr(ngrok, "executable", lambda: str(source))
    calls = []

    def run(args, **kwargs):
        assert args[1] == "version", "Self-update must never run"
        candidate = Path(args[0])
        assert candidate != target
        if installed:
            assert target.read_bytes() == b"working-installed-agent"
        if args[1] == "update":
            candidate.rename(candidate.with_name(".ngrok.exe.old"))
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=0, stdout="ngrok version 3.40.0\n")

    def download(candidate):
        calls.append(candidate)
        candidate.write_bytes(b"verified-official-agent")

    monkeypatch.setattr(ngrok.subprocess, "run", run)
    monkeypatch.setattr(ngrok_download, "download_agent", download)
    ngrok.update_agent(tmp_path)
    assert calls and target.read_bytes() == b"verified-official-agent"
    assert source.read_bytes() == b"old-bootstrap"
    assert backup.read_bytes() == b"previous-user-backup"
    assert not list(tmp_path.glob("ngrok-update-*"))


def test_failed_download_preserves_installed_agent(tmp_path, monkeypatch):
    from scripts import ngrok_download

    target = tmp_path / "ngrok-agent/ngrok.exe"
    target.parent.mkdir()
    target.write_bytes(b"working-agent")

    def failed_download(path):
        raise ValueError("Official download refused")

    monkeypatch.setattr(ngrok_download, "download_agent", failed_download)
    with pytest.raises(ValueError, match="refused"):
        ngrok.update_agent(tmp_path)
    assert target.read_bytes() == b"working-agent"
    assert not list(tmp_path.glob("ngrok-update-*"))


@pytest.mark.parametrize(
    "line",
    ["unknown flag: --url", "error reading configuration", "ERROR ERR_NGROK_105 private-token"],
)
def test_startup_error_classified_without_raw_output(line, capsys):
    events, failures = queue.Queue(), []
    ngrok.read_output(io.StringIO(line + "\n"), events, "https://test.ngrok-free.dev", failures)
    assert failures and events.get_nowait() is False
    assert "private-token" not in " ".join(failures) + capsys.readouterr().out


def test_update_command_does_not_read_tokens_or_grant_database(tmp_path, monkeypatch):
    import sys

    from scripts import tester_host as host

    monkeypatch.setattr(
        host, "os", SimpleNamespace(name="nt", environ={"LOCALAPPDATA": str(tmp_path)})
    )
    monkeypatch.setattr(host, "Store", lambda *a, **k: pytest.fail("No database"))
    monkeypatch.setattr(host, "load_secret", lambda *a: pytest.fail("No token reads"))
    called = []
    monkeypatch.setattr(host, "host_lock", lambda root: nullcontext())
    monkeypatch.setattr(ngrok, "update_agent", lambda root: called.append(root))
    monkeypatch.setattr(sys, "argv", ["tester_host.py", "update-ngrok"])
    assert host.main() == 0 and called == [tmp_path / "DND-NCFU-Host"]


@pytest.mark.parametrize("outcome", ["rejected", "timeout"])
def test_failed_update_keeps_credentials_and_cleans_config(tmp_path, monkeypatch, capsys, outcome):
    import subprocess

    target = tmp_path / "ngrok-agent/ngrok.exe"
    target.parent.mkdir()
    target.write_bytes(b"old-agent")
    secret = tmp_path / "ngrok-token.bin"
    secret.write_bytes(b"protected-existing-secret")

    def run(*args, **kwargs):
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("fake", 180, output="private-token")
        return SimpleNamespace(returncode=1, stdout="private-token", stderr="private-path")

    from scripts import ngrok_download

    monkeypatch.setattr(ngrok_download, "download_agent", lambda p: p.write_bytes(b"candidate"))
    monkeypatch.setattr(ngrok.subprocess, "run", run)
    with pytest.raises(ValueError) as error:
        ngrok.update_agent(tmp_path)
    assert "private" not in str(error.value) + capsys.readouterr().out
    assert secret.read_bytes() == b"protected-existing-secret"
    assert target.read_bytes() == b"old-agent" and not list(tmp_path.glob("*.yml"))


def test_local_zip_cli_reaches_installer_without_keys(tmp_path, monkeypatch):
    import sys

    from scripts import tester_host as host

    monkeypatch.setattr(
        host, "os", SimpleNamespace(name="nt", environ={"LOCALAPPDATA": str(tmp_path)})
    )
    monkeypatch.setattr(host, "Store", lambda *a, **k: pytest.fail("No database"))
    monkeypatch.setattr(host, "load_secret", lambda *a: pytest.fail("No token reads"))
    monkeypatch.setattr(host, "host_lock", lambda root: nullcontext())
    called = []
    monkeypatch.setattr(ngrok, "update_agent", lambda root, **kw: called.append((root, kw)))
    monkeypatch.setattr(
        sys, "argv", ["tester_host.py", "update-ngrok", "--archive", "official.zip"]
    )
    assert host.main() == 0
    assert called == [(tmp_path / "DND-NCFU-Host", {"archive_path": Path("official.zip")})]


def test_local_archive_installs_atomically_and_preserves_source(tmp_path, monkeypatch):
    from scripts import ngrok_download

    source = tmp_path / "official.zip"
    source.write_bytes(b"official-archive")
    target = tmp_path / "ngrok-agent/ngrok.exe"
    target.parent.mkdir()
    target.write_bytes(b"old-agent")

    def install(candidate, archive_path):
        assert archive_path == source
        assert target.read_bytes() == b"old-agent"
        candidate.write_bytes(b"verified-binary")

    monkeypatch.setattr(ngrok_download, "download_agent", install)
    monkeypatch.setattr(ngrok, "require_supported", lambda path: (3, 39, 13))
    ngrok.update_agent(tmp_path, archive_path=source)
    assert target.read_bytes() == b"verified-binary"
    assert source.read_bytes() == b"official-archive"
