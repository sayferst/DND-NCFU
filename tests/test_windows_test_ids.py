"""Regression for the actual Windows PYTEST_CURRENT_TEST overflow reported by the owner."""

import subprocess
import sys
from pathlib import Path


def test_large_prompt_parameter_has_a_short_collected_id():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/test_master_configuration.py",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=True,
    )
    ids = [
        line
        for line in result.stdout.splitlines()
        if "test_invalid_instruction_is_rejected_instead_of_silently_using_another[" in line
    ]
    assert len(ids) == 4
    assert any("[oversized]" in id for id in ids)
    assert all(len(id + " (teardown)") < 32767 for id in ids)
