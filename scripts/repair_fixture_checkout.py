"""Restore only a known CRLF-converted fixture; never edit saves or expected hashes."""

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

FIXTURE = "tests/fixtures/save-v15.json"
SOURCE = "tests/fixtures/save-v15.source.json"


def committed_bytes(root: Path, relative: str) -> bytes:
    """Read the committed blob as bytes, without checkout filters or console encoding."""
    result = subprocess.run(
        ["git", "cat-file", "blob", "HEAD:" + relative],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"Cannot read committed reference: {relative}. Run git pull first.")
    return result.stdout


def reference_bytes(root: Path) -> bytes:
    original = committed_bytes(root, FIXTURE)
    source = json.loads(committed_bytes(root, SOURCE).decode("utf-8"))
    if hashlib.sha256(original).hexdigest() != source["sha256"]:
        raise ValueError("Committed fixture does not match its source SHA-256. Nothing changed.")
    return original


def repair_fixture(root: Path) -> bool:
    """Return whether the working copy was repaired; refuse every other modification."""
    original = reference_bytes(root)
    fixture = root / FIXTURE
    if fixture.is_symlink():
        raise ValueError("Fixture is a symbolic link. Nothing changed.")
    current = fixture.read_bytes()
    if current == original:
        return False
    if b"\r" in original or current != original.replace(b"\n", b"\r\n"):
        raise ValueError("Fixture has changes other than LF to CRLF. Nothing changed.")

    # Do not depend on Git's stat cache or pass binary JSON through PowerShell.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=fixture.parent, suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(original)
        os.replace(temporary, fixture)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if fixture.read_bytes() != original:
        raise ValueError("Fixture verification failed after writing. Do not run the game yet.")
    return True


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        changed = repair_fixture(root)
    except (OSError, ValueError, KeyError) as error:
        print(f"Fixture repair stopped: {error}", flush=True)
        return 1
    state = "Restored original LF bytes" if changed else "Already matches committed bytes"
    print(f"{state}: {FIXTURE}", flush=True)
    print("SHA-256 verified. Expected hashes and game saves were not changed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
