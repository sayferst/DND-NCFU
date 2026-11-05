"""Transfer is executable offline and contains no owner data or fictitious weights."""

import hashlib
import json
import subprocess
import sys
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from training.model_profiles import validate_faun_cuda
from training.prepare_faun_transfer import prepare


def test_transfer_contains_portable_configs_and_offline_preflight(tmp_path):
    path = tmp_path / "transfer.zip"
    result = prepare(path)
    assert result["dataset_status"] == "BLOCKED_DATA"
    assert result["training_steps"] == 0
    assert not result["weights_included"] and not result["dataset_included"]
    with ZipFile(path) as archive:
        for name, digest in result["files_sha256"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
        smoke = json.loads(archive.read("faun-smoke.json"))
        full = json.loads(archive.read("faun-full.json"))
        assert smoke["output"] != full["output"]
        assert smoke["dataset_sha256"] is None and smoke["double_quant"] is True
        assert smoke["model_path"] == "models/faun-reviewed-base"
        assert not any(n.endswith((".gguf", ".safetensors", ".jsonl")) for n in archive.namelist())
        archive.extractall(tmp_path / "gpu")
    run = subprocess.run(
        [sys.executable, "-m", "training.train_lora", "--config", "faun-smoke.json", "--dry-run"],
        cwd=tmp_path / "gpu",
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(run.stdout)["training_started"] is False
    assert "BLOCKED_DATA" in run.stdout
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        prepare(path)
    assert path.read_bytes() == before


def test_unreviewed_dataset_cannot_be_bound_or_published(tmp_path):
    dataset = tmp_path / "private"
    dataset.mkdir()
    (dataset / "manifest.json").write_text('{"status":"BLOCKED_DATA"}')
    output = tmp_path / "transfer.zip"
    with pytest.raises(ValueError, match="BLOCKED_DATA"):
        prepare(output, dataset=dataset)
    assert not output.exists()


@pytest.mark.parametrize(
    "available,vram,bf16,allowed",
    [
        (False, 24, True, False),
        (True, 8, True, False),
        (True, 24, False, False),
        (True, 24, True, True),
    ],
)
def test_actual_selected_cuda_device_must_fit_config(available, vram, bf16, allowed):
    def properties(index):
        assert index == 0
        return SimpleNamespace(total_memory=vram * 1024**3)

    torch = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: available,
            get_device_properties=properties,
            is_bf16_supported=lambda: bf16,
        )
    )
    if allowed:
        validate_faun_cuda(torch)
    else:
        with pytest.raises(ValueError, match="BLOCKED_HARDWARE"):
            validate_faun_cuda(torch)


def test_reviewed_split_hash_is_bound_without_copying_the_dataset(tmp_path):
    from test_training_pipeline import sample

    folder = tmp_path / "reviewed"
    folder.mkdir()
    hashes = {}
    for i, name in enumerate(("train", "val", "test")):
        raw = json.dumps(sample(i, str(i))).encode()
        (folder / (name + ".jsonl")).write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "status": "READY",
                "privacy_review_confirmed": True,
                "sha256": "fixture-reviewed-hash",
                "file_sha256": hashes,
            }
        )
    )
    (folder / "private-not-for-transfer.txt").write_text("Private fixture")
    path = tmp_path / "bound.zip"
    report = prepare(path, dataset=folder)
    assert report["dataset_sha256"] == "fixture-reviewed-hash"
    assert not report["dataset_included"]
    with ZipFile(path) as archive:
        assert (
            json.loads(archive.read("faun-full.json"))["dataset_sha256"] == "fixture-reviewed-hash"
        )
        assert not any(
            "private-not-for-transfer" in n or n.endswith(".jsonl") for n in archive.namelist()
        )
