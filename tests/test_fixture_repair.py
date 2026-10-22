"""A narrowly scoped repair must preserve provenance and refuse unrelated changes."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.repair_fixture_checkout import FIXTURE, SOURCE, reference_bytes, repair_fixture


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "папка проекта"
    root.mkdir()

    def git(*arguments):
        return subprocess.run(
            [
                "git",
                "-c",
                "core.autocrlf=true",
                "-c",
                "core.safecrlf=false",
                "-c",
                "core.attributesfile=" + os.devnull,
                "-c",
                "core.hooksPath=" + (tmp_path / "empty-hooks").as_posix(),
                "-c",
                "commit.gpgsign=false",
                "-c",
                "user.name=Fixture regression",
                "-c",
                "user.email=fixture@example.invalid",
                *arguments,
            ],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout

    git("init", "--quiet")
    original = reference_bytes(Path(__file__).resolve().parents[1])
    path = root / FIXTURE
    path.parent.mkdir(parents=True)
    path.write_bytes(original)
    (root / SOURCE).write_text(
        json.dumps({"sha256": hashlib.sha256(original).hexdigest()}), encoding="utf-8"
    )
    (root / ".gitattributes").write_text("tests/fixtures/*.json -text\n", encoding="utf-8")
    git("add", "--all")
    git("commit", "--quiet", "-m", "Original immutable fixture")
    return root, path, original, git


def test_repair_exact_windows_bytes_even_if_git_reports_clean_and_repeat_safely(checkout):
    root, path, original, git = checkout
    path.write_bytes(original.replace(b"\n", b"\r\n"))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "b1d9736c8d31f59f331da4e74ee2850f7f211488b2bbd6ff59f9f1e5b1d420f2"
    )
    git("update-index", "--assume-unchanged", "--", FIXTURE)
    assert git("status", "--porcelain") == b""
    index_before = git("show", ":" + FIXTURE)
    source_before = (root / SOURCE).read_bytes()
    saves = root / "saves"
    saves.mkdir()
    save = saves / "slot-1.json"
    save.write_bytes(b"user save: \r\n do not modify")

    assert repair_fixture(root) is True
    assert path.read_bytes() == original
    assert repair_fixture(root) is False
    assert git("show", ":" + FIXTURE) == index_before
    assert (root / SOURCE).read_bytes() == source_before
    assert save.read_bytes() == b"user save: \r\n do not modify"
    assert list(path.parent.glob("*.tmp")) == []


def test_current_lf_fixture_is_left_untouched(checkout):
    root, path, original, _ = checkout
    before = path.stat().st_mtime_ns
    assert repair_fixture(root) is False
    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == before


@pytest.mark.parametrize("damage", ["mixed", "extra", "truncated", "double-cr", "edited-json"])
def test_refuse_every_change_other_than_exact_lf_to_crlf(checkout, damage):
    root, path, original, _ = checkout
    modified = {
        "mixed": original.replace(b"\n", b"\r\n", 1),
        "extra": original.replace(b"\n", b"\r\n") + b" ",
        "truncated": original[:-10],
        "double-cr": original.replace(b"\n", b"\r\r\n"),
        "edited-json": original.replace(b'"schema_version": 15', b'"schema_version": 999'),
    }[damage]
    path.write_bytes(modified)
    with pytest.raises(ValueError, match="changes other than LF to CRLF"):
        repair_fixture(root)
    assert path.read_bytes() == modified


def test_bad_committed_checksum_is_never_recalculated_or_accepted(checkout):
    root, path, original, git = checkout
    (root / SOURCE).write_text(json.dumps({"sha256": "0" * 64}), encoding="utf-8")
    git("add", "--", SOURCE)
    git("commit", "--quiet", "-m", "Damaged provenance")
    converted = original.replace(b"\n", b"\r\n")
    path.write_bytes(converted)
    with pytest.raises(ValueError, match="does not match its source SHA-256"):
        repair_fixture(root)
    assert path.read_bytes() == converted
    assert json.loads((root / SOURCE).read_text(encoding="utf-8"))["sha256"] == "0" * 64


def test_missing_fixture_is_not_silently_recreated(checkout):
    root, path, _, _ = checkout
    path.unlink()
    with pytest.raises(FileNotFoundError):
        repair_fixture(root)
    assert not path.exists()


def test_missing_git_reference_is_reported_without_changing_files(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    with pytest.raises(ValueError, match="Cannot read committed reference"):
        repair_fixture(tmp_path)


def test_failed_replace_preserves_old_file_and_cleans_temporary_file(checkout, monkeypatch):
    root, path, original, _ = checkout
    converted = original.replace(b"\n", b"\r\n")
    path.write_bytes(converted)

    def denied(*_):
        raise PermissionError("File is locked")

    monkeypatch.setattr("scripts.repair_fixture_checkout.os.replace", denied)
    with pytest.raises(PermissionError, match="File is locked"):
        repair_fixture(root)
    assert path.read_bytes() == converted
    assert list(path.parent.glob("*.tmp")) == []
