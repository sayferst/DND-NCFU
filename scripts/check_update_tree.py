"""Check update cleanliness, tolerating only a byte-identical fixture status."""

import subprocess
from pathlib import Path

from scripts.repair_fixture_checkout import FIXTURE, reference_bytes


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def check(root):
    entries = git(root, "status", "--porcelain=v1", "-z").split(b"\0")
    entries = [entry for entry in entries if entry]
    if not entries:
        return True
    if entries != [b" M " + FIXTURE.encode()]:
        return False
    original = reference_bytes(root)
    fixture = root / FIXTURE
    return (
        not fixture.is_symlink()
        and fixture.read_bytes() == original
        and git(root, "show", ":" + FIXTURE) == original
    )


if __name__ == "__main__":
    try:
        ok = check(Path(__file__).resolve().parents[1])
    except (OSError, ValueError, subprocess.CalledProcessError):
        ok = False
    print("Working tree verified." if ok else "Local changes found. Update stopped.")
    raise SystemExit(0 if ok else 1)
