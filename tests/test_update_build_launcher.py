"""Actual PowerShell updater against disposable local Git remotes; no user checkout."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

BRANCH = "feature/unified-rpg-automatic-gm"
ROOT = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def checkout(tmp_path):
    shell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not shell:
        pytest.skip("Actual PowerShell updater integration requires Windows/PowerShell")
    remote, owner, other = (tmp_path / p for p in ("remote.git", "owner", "other"))
    git(tmp_path, "init", "--bare", str(remote))
    git(tmp_path, "clone", str(remote), str(owner))
    for path in (owner,):
        git(path, "config", "user.name", "Updater test")
        git(path, "config", "user.email", "test@example.invalid")
    git(owner, "checkout", "-b", BRANCH)
    (owner / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/update_and_build.ps1", owner / "scripts/update_and_build.ps1")
    (owner / "payload.txt").write_text("version one", encoding="utf-8")
    git(owner, "add", ".")
    git(owner, "commit", "-m", "baseline")
    git(owner, "push", "-u", "origin", BRANCH)
    git(tmp_path, "clone", "-b", BRANCH, str(remote), str(other))
    git(other, "config", "user.name", "Updater test")
    git(other, "config", "user.email", "test@example.invalid")
    return shell, owner, other


def run(checkout, *, active_host=False):
    shell, owner, _ = checkout
    environment = os.environ.copy()
    environment["DND_UPDATER_TEST_SCRIPT"] = str(owner / "scripts/update_and_build.ps1")
    environment["DND_UPDATER_TEST_HOST"] = "1" if active_host else "0"
    # Only this child shell shadows process enumeration. Never query/stop a real host.
    command = (
        "function Get-CimInstance { param($ClassName, $Filter); "
        "if ($env:DND_UPDATER_TEST_HOST -eq '1') { "
        "[pscustomobject]@{CommandLine='python.exe tester_host.py start'} } }; "
        "& $env:DND_UPDATER_TEST_SCRIPT -VerifyOnly"
    )
    return subprocess.run(
        [
            shell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def publish(other):
    (other / "payload.txt").write_text("version two", encoding="utf-8")
    git(other, "add", ".")
    git(other, "commit", "-m", "new version")
    git(other, "push")
    return git(other, "rev-parse", "HEAD")


def test_current_checkout_prints_actual_sha(checkout):
    result = run(checkout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Build source commit: " + git(checkout[1], "rev-parse", "HEAD") in result.stdout


def test_fetches_and_fast_forwards_only_current_release_branch(checkout):
    expected = publish(checkout[2])
    result = run(checkout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(checkout[1], "rev-parse", "HEAD") == expected
    assert git(checkout[1], "branch", "--show-current") == BRANCH


def test_wrong_branch_never_switches_or_updates(checkout):
    git(checkout[1], "checkout", "-b", "keep-my-work")
    before = git(checkout[1], "rev-parse", "HEAD")
    publish(checkout[2])
    result = run(checkout)
    assert result.returncode != 0 and BRANCH in result.stdout
    assert git(checkout[1], "branch", "--show-current") == "keep-my-work"
    assert git(checkout[1], "rev-parse", "HEAD") == before


def test_dirty_checkout_with_remote_changes_is_preserved(checkout):
    path = checkout[1] / "payload.txt"
    path.write_text("unsaved owner work", encoding="utf-8")
    before = git(checkout[1], "rev-parse", "HEAD")
    publish(checkout[2])
    result = run(checkout)
    assert result.returncode != 0
    assert git(checkout[1], "rev-parse", "HEAD") == before
    assert path.read_text(encoding="utf-8") == "unsaved owner work"


def test_active_host_prevents_fast_forward_without_touching_checkout(checkout):
    before = git(checkout[1], "rev-parse", "HEAD")
    expected = publish(checkout[2])
    result = run(checkout, active_host=True)
    assert result.returncode != 0
    assert "Stop START_HOST.bat" in result.stdout + result.stderr
    assert git(checkout[1], "rev-parse", "HEAD") == before
    assert git(checkout[1], "rev-parse", "origin/" + BRANCH) == expected
