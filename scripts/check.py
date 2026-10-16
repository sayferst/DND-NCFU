"""Run the environment checks from any working directory, without network calls."""

import platform
import sqlite3
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    print(f"Platform: {platform.system()} {platform.machine()}", flush=True)
    print(f"Python: {platform.python_version()}; SQLite: {sqlite3.sqlite_version}", flush=True)
    if sys.version_info[:2] != (3, 12) or sys.prefix == sys.base_prefix:
        print("Use Python 3.12 from the project's .venv.", flush=True)
        return 1
    commands = [
        ["git", "--version"],
        [sys.executable, "-m", "pip", "--no-cache-dir", "check"],
        [sys.executable, "-m", "pytest"],
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
    ]
    for command in commands:
        print("Running: " + " ".join(command), flush=True)
        try:
            result = subprocess.run(command, cwd=root, check=False)
        except OSError as error:
            print(f"Cannot start check: {error}", flush=True)
            return 1
        if result.returncode:
            return result.returncode
    print("Environment checks passed. Game and Windows UI are not tested.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
