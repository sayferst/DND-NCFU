"""Portable research deliveries check all bytes and reject unsafe archive paths."""

import hashlib
import json
from zipfile import ZipFile

import pytest

from training.gm_review_transfer import verify_archive


def archive(path, *, name="review/answer.txt", payload="Привет!", declared="Привет!"):
    raw = declared.encode("utf-8")
    manifest = {
        "schema": "gm-source-review-transfer-v1",
        "status": "RESEARCH_AND_OWNER_REVIEW_NOT_TRAIN_READY",
        "files": {name: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}},
    }
    with ZipFile(path, "x") as z:
        z.writestr(name, payload.encode("utf-8"))
        z.writestr("transfer-manifest.json", json.dumps(manifest))


def test_every_byte_is_verified_without_running_a_model(tmp_path):
    path = tmp_path / "portable.zip"
    archive(path)
    result = verify_archive(path)
    assert result["files"] == 1 and result["training_steps"] == 0
    assert result["status"] == "ALL_TRANSFER_PAYLOAD_HASHES_VERIFIED_NOT_TRAIN_READY"


def test_payload_change_fails_the_portable_manifest(tmp_path):
    path = tmp_path / "tampered.zip"
    archive(path, payload="Иной ответ.")
    with pytest.raises(ValueError, match="payload hash"):
        verify_archive(path)


@pytest.mark.parametrize(
    "name", ["../answer.txt", "/answer.txt", "C:answer.txt", "review\\answer.txt"]
)
def test_unsafe_windows_and_posix_paths_are_rejected(tmp_path, name):
    path = tmp_path / "unsafe.zip"
    archive(path, name=name)
    with pytest.raises(ValueError, match="Unsafe transfer"):
        verify_archive(path)


def test_duplicate_members_are_rejected(tmp_path):
    path = tmp_path / "duplicate.zip"
    archive(path)
    with ZipFile(path, "a") as z, pytest.warns(UserWarning):
        z.writestr("review/answer.txt", "other")
    with pytest.raises(ValueError, match="Duplicate archive"):
        verify_archive(path)
