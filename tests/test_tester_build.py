"""Tester Setup preflight and handoff with fake Windows compiler/DPAPI, no activation."""

import json
import os
import subprocess
import time
import urllib.error
from pathlib import Path

import pytest

from scripts import tester_host as host
from server.gateway import Store


@pytest.mark.parametrize(
    "variable,relative",
    [
        ("ProgramFiles(x86)", "Inno Setup 6/ISCC.exe"),
        ("ProgramFiles", "Inno Setup 6/ISCC.exe"),
        ("LOCALAPPDATA", "Programs/Inno Setup 6/ISCC.exe"),
    ],
)
def test_inno_installed_outside_path_is_found(tmp_path, monkeypatch, variable, relative):
    for name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(host.shutil, "which", lambda _: None)
    monkeypatch.setenv(variable, str(tmp_path))
    compiler = tmp_path / relative
    compiler.parent.mkdir(parents=True)
    compiler.touch()
    assert host.inno_compiler() == str(compiler)


def test_inno_path_has_priority_over_other_installations(tmp_path, monkeypatch):
    compiler = tmp_path / "custom compiler/ISCC.exe"
    compiler.parent.mkdir()
    compiler.touch()
    monkeypatch.setattr(host.shutil, "which", lambda _: str(compiler))
    assert host.inno_compiler() == str(compiler)


@pytest.fixture
def build_env(tmp_path, monkeypatch):
    root, project = tmp_path / "owner", tmp_path / "checkout"
    root.mkdir()
    (project / "dist").mkdir(parents=True)
    compiler = tmp_path / "Programs/Inno Setup 6/ISCC.exe"
    compiler.parent.mkdir(parents=True)
    compiler.touch()
    monkeypatch.setattr(host, "ROOT", project)
    monkeypatch.setattr(host, "inno_compiler", lambda: str(compiler))
    monkeypatch.setattr(host, "fetch", lambda *a, **k: {"endpoint": "https://test.example/api/v1"})
    monkeypatch.setattr(host, "check_health", lambda endpoint: None)
    ready = {
        "pid": os.getpid(),
        "discovery": host.DISCOVERY,
        "verification_key": "fake-public-key",
        "sequence": 7,
    }
    (root / "host-ready.json").write_text(json.dumps(ready))
    secrets = {}

    def load(path):
        assert path.name == "activation-tester1.bin"  # Never reads the owner's RouterAI key.
        return secrets.get(path.name, "")

    monkeypatch.setattr(host, "load_secret", load)
    monkeypatch.setattr(host, "save_secret", lambda path, value: secrets.update({path.name: value}))
    store = Store(root / "test.sqlite3", global_budget=100_000_000)
    return root, project, compiler, secrets, store


def test_build_uses_user_inno_fresh_exact_setup_and_reuses_grant(build_env, monkeypatch):
    root, project, compiler, secrets, store = build_env
    unrelated = project / "dist/UnrelatedSetup.exe"
    unrelated.write_bytes(b"do not send")
    os.utime(unrelated, (time.time() + 86400, time.time() + 86400))
    codes = []

    def run(command, **kwargs):
        assert command[command.index("-InnoCompiler") + 1] == str(compiler)
        assert kwargs == {"cwd": project, "check": True}
        bootstrap = Path(command[command.index("-BootstrapFile") + 1])
        codes.append(json.loads(bootstrap.read_text())["code"])
        assert codes[-1] not in command
        (project / "dist/DND-NCFU-Setup.exe").write_bytes(
            b"MZ-personal-new-" + str(len(codes)).encode()
        )

    monkeypatch.setattr(host.subprocess, "run", run)
    host.build(root, store, "tester1")
    before = store.summary()
    host.build(root, store, "tester1")
    assert store.summary() == before
    assert len(codes) == 2 and codes[0] == codes[1] == secrets["activation-tester1.bin"]
    assert before[0]["budget"] == 100_000_000 and before[0]["calls"] == 0
    assert (project / "dist/Tester-tester1/DND-NCFU-Setup.exe").read_bytes() == b"MZ-personal-new-2"
    assert sorted(p.name for p in root.glob("*.json")) == ["host-ready.json"]


@pytest.mark.parametrize("stage", ["checks", "self-check", "smoke-test", "inno"])
def test_build_reports_failed_stage_and_cleans_temporary_files(build_env, monkeypatch, stage):
    root, project, _, secrets, store = build_env

    def run(command, **kwargs):
        report = Path(command[command.index("-BuildStatusFile") + 1])
        report.write_text(json.dumps({"stage": stage}), encoding="utf-8-sig")
        raise subprocess.CalledProcessError(1, ["private path and credential"])

    monkeypatch.setattr(host.subprocess, "run", run)
    with pytest.raises(ValueError, match=host.BUILD_STAGES[stage]) as error:
        host.build(root, store, "tester1")
    assert "private path" not in str(error.value)
    assert sorted(p.name for p in root.glob("*.json")) == ["host-ready.json"]
    assert not (project / "dist/Tester-tester1").exists()
    assert store.summary()[0]["calls"] == 0 and len(secrets) == 1


@pytest.mark.parametrize(
    "failure", ["missing_ready", "dead_host", "bad_signature", "http530", "inno"]
)
def test_preflight_failure_does_not_issue_grant(build_env, monkeypatch, failure):
    root, _, _, secrets, store = build_env
    if failure == "missing_ready":
        (root / "host-ready.json").unlink()
    elif failure == "dead_host":
        monkeypatch.setattr(host, "host_process_alive", lambda pid: False)
    elif failure == "bad_signature":

        def invalid(*a, **k):
            raise ValueError("untrusted private raw response")

        monkeypatch.setattr(host, "fetch", invalid)
    elif failure == "http530":

        def unavailable(endpoint):
            raise urllib.error.HTTPError(endpoint, 530, "private error body", {}, None)

        monkeypatch.setattr(host, "check_health", unavailable)
    else:
        monkeypatch.setattr(host, "inno_compiler", lambda: "")
    with pytest.raises(ValueError) as error:
        host.build(root, store, "tester1")
    if failure == "http530":
        assert "HTTP 530" in str(error.value)
    assert "private" not in str(error.value)
    assert not store.summary() and not secrets


def test_successful_process_cannot_hand_over_an_old_setup(build_env, monkeypatch):
    root, project, _, _, store = build_env
    (project / "dist/DND-NCFU-Setup.exe").write_bytes(b"old installer")
    monkeypatch.setattr(host.subprocess, "run", lambda *a, **k: None)
    with pytest.raises(ValueError, match="не создал новый"):
        host.build(root, store, "tester1")
    assert not (project / "dist/Tester-tester1").exists()


def test_host_pid_validation():
    assert host.host_process_alive(os.getpid())
    assert not host.host_process_alive(0)
    assert not host.host_process_alive("1")
