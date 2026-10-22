"""Regression for the actual Windows PYTEST_CURRENT_TEST overflow reported by the owner."""

import subprocess
import sys
from pathlib import Path


def test_all_collected_ids_fit_windows_current_test_environment():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=True,
    )
    all_ids = [line for line in result.stdout.splitlines() if "::" in line]
    assert all_ids
    assert all(len((id + " (teardown)").encode("utf-16-le")) // 2 < 32767 for id in all_ids)
    assert any("test_invalid_dns_reply_is_not_used[oversized]" in id for id in all_ids)
    ids = [
        line
        for line in result.stdout.splitlines()
        if "test_invalid_instruction_is_rejected_instead_of_silently_using_another[" in line
    ]
    assert len(ids) == 4
    assert any("[oversized]" in id for id in ids)
    assert all(len(id + " (teardown)") < 32767 for id in ids)
