"""Process isolation must neither omit failures nor lose a test file."""

import json

from scripts.check_batches import run


def test_isolated_processes_cover_every_file_and_count_skips(tmp_path):
    folder = tmp_path / "tests"
    folder.mkdir()
    (folder / "test_one.py").write_text("def test_one():\n    assert True\n", encoding="utf-8")
    (folder / "test_two.py").write_text(
        "import pytest\ndef test_two():\n    pytest.skip('intentional')\n", encoding="utf-8"
    )
    assert run(tmp_path, batch_size=1) == 0
    summary = json.loads(
        next((tmp_path / "build").rglob("summary.json")).read_text(encoding="utf-8")
    )
    assert summary["passed"] == 1 and summary["skipped"] == 1
    assert len(summary["batches"]) == len(summary["expected_files"]) == 2


def test_failed_batch_never_returns_a_complete_report(tmp_path):
    folder = tmp_path / "tests"
    folder.mkdir()
    (folder / "test_bad.py").write_text("def test_bad():\n    assert False\n", encoding="utf-8")
    assert run(tmp_path, batch_size=1) == 1
    summary = json.loads(
        next((tmp_path / "build").rglob("summary.json")).read_text(encoding="utf-8")
    )
    assert not summary["complete"] and summary["failed"] == 1
