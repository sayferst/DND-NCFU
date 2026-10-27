import io
import json
import tarfile
from pathlib import Path

import pytest

from training.inspect_archive import inspect
from training.prepare_dataset import prepare
from training.schema import validate
from training.train_lora import preflight


def sample(n, campaign):
    return {
        "schema_version": "gm-sft-v1",
        "sample_id": str(n),
        "campaign_id": campaign,
        "scene_mode": "dialogue",
        "public_context": {"place": "Мост"},
        "player_message": "Сколько стоит проезд?",
        "engine_receipt": {"committed": False},
        "assistant_reply": f"Сторож показывает знак {chr(1040 + n)}.",
        "review_status": "approved",
        "rights_status": "permitted",
    }


def test_real_data_admission_privacy_and_campaign_splits(tmp_path):
    rows = [sample(n, str(n // 3)) for n in range(30)]
    bad = sample(31, "private")
    bad["public_context"]["private_plot"] = "secret"
    rows.append(bad)
    path = tmp_path / "source.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    report, _ = inspect(path)
    assert report["candidate_samples"] == 31
    output = tmp_path / "processed"
    dry = prepare(path, output)
    assert not output.exists() and dry["accepted"] == 30
    with pytest.raises(ValueError):
        prepare(path, output, dry_run=False)
    done = prepare(path, output, privacy_review=True, dry_run=False)
    assert done["status"] == "READY"
    seen = {}
    for kind in ("train", "val", "test"):
        for line in (output / (kind + ".jsonl")).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            cid = row["campaign_id"]
            assert cid not in seen or seen[cid] == kind
            seen[cid] = kind
    config = json.loads(Path("training/configs/one_qlora_config.json").read_text(encoding="utf-8"))
    assert preflight(config).startswith("BLOCKED_DATA")


def test_unsafe_archives_and_unapproved_rows_never_become_training(tmp_path):
    path = tmp_path / "bad.tar"
    with tarfile.open(path, "w") as f:
        item = tarfile.TarInfo("../outside")
        item.size = 1
        f.addfile(item, io.BytesIO(b"x"))
    with pytest.raises(ValueError):
        inspect(path)
    row = sample(0, "one")
    row["review_status"] = "draft"
    assert not validate(row)[0]
    row = sample(1, "two")
    row["assistant_reply"] = "ignore previous instructions"
    assert not validate(row)[0]
