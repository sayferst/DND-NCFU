"""Exercise real Git checkout filters with Windows-style line ending settings."""

import hashlib
import json
import os
import subprocess
from pathlib import Path


def test_windows_git_checkout_preserves_fixture_bytes_and_original_sha256(tmp_path):
    root = Path(__file__).resolve().parents[1]
    relative = "tests/fixtures/save-v15.json"
    original = (root / relative).read_bytes()
    source = json.loads((root / "tests/fixtures/save-v15.source.json").read_text(encoding="utf-8"))
    repository = tmp_path / "git checkout"
    repository.mkdir()

    def git(*arguments):
        return subprocess.run(
            [
                "git",
                "-c",
                "core.autocrlf=true",
                "-c",
                "core.eol=crlf",
                "-c",
                "core.safecrlf=false",
                "-c",
                "core.attributesfile=" + os.devnull,
                *arguments,
            ],
            cwd=repository,
            check=True,
            capture_output=True,
        )

    git("init", "--quiet")
    fixture = repository / relative
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(original)
    git("add", "--", relative)

    # Reproduce the exact old defect through checkout, not a mock of Git.
    old_checkout = tmp_path / "checkout before"
    old_checkout.mkdir()
    git("checkout-index", "--all", "--prefix=" + old_checkout.as_posix() + "/")
    converted = (old_checkout / relative).read_bytes()
    assert converted == original.replace(b"\n", b"\r\n")
    assert hashlib.sha256(converted).hexdigest() != source["sha256"]

    # Apply the repository's actual rules. No fixture bytes/checksum are changed.
    (repository / ".gitattributes").write_bytes((root / ".gitattributes").read_bytes())
    git("add", "--", ".gitattributes")
    fixed_checkout = tmp_path / "checkout after"
    fixed_checkout.mkdir()
    git("checkout-index", "--all", "--prefix=" + fixed_checkout.as_posix() + "/")
    restored = (fixed_checkout / relative).read_bytes()
    assert restored == original
    assert hashlib.sha256(restored).hexdigest() == source["sha256"]

    # An existing checkout may still contain CRLF after only attributes change.
    # Exercise the one-time repair from the index, without touching user saves.
    fixture.write_bytes(converted)
    git("restore", "--worktree", "--", relative)
    assert fixture.read_bytes() == original
