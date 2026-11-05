"""Package research data, review sheets and pinned tools without weights or training approval."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from training.fetch_faun_tokenizer import HASHES
from training.gm_candidate_audit import file_digest
from training.gm_research_corpus import verify
from training.setup_faun_gpu import FILES, ROOT

GUIDE = """# DND-NCFU: исходные данные и проверка RU/EN

Этот архив пока НЕ является готовым русским корпусом для обучения.
data/native содержит проверенный по структуре отбор на языках оригиналов.
review содержит40 пар для личной оценки; сцены кратко изложены на RU/EN,
полные исходные контексты и реплики сохранены в review-cases.jsonl.
Оценки человека пустые. Смысловая проверка всего корпуса ещё не выполнена.

1. Открой review/DND_NCFU_REVIEW_40_RU_EN.xlsx. На листе «40 примеров»
   заполни I–O: понятность, верность сцене, стиль, смысл перевода, решение,
   при необходимости исправленный русский ответ и замечания.
2. Проверка архива и данных не требует аренды GPU, весов Faun или установки игры.
   В PowerShell из распакованной папки (Python3.12 должен уже существовать):

```powershell
Set-Location .\\tools
$env:PYTHONPATH = (Resolve-Path .\\src).Path
py -3.12 -m training.gm_research_corpus verify --directory ..\\data\\native
py -3.12 -m training.gm_review_packet import-review `
  --packet ..\\review --workbook ..\\review\\DND_NCFU_REVIEW_40_RU_EN.xlsx `
  --output ..\\owner-labels.json
```

Не заполненный владельцем Excel вернёт reviewed_rows=0. Изменённые исходники,
оценка без решения и непроверенные исправления не становятся одобрением.
Личная оценка40 примеров не одобряет автоматически все остальные строки.

tools/docs/intelligent_gm/SOURCE_DATA_V5.md описывает источники, покрытие и границы.
audits содержит настоящие отчёты и проверку токенизатора. FAUN-веса,
большой raw-архив, установка зависимостей и обучение автоматически не запускаются.
Старый готовый комплект с1100 эталонными исполнениями существует отдельно.

Для QLoRA затем нужны: завершённые и проверенные RU/EN версии, новая версия
корпуса с её хэшами, повторный расчёт токенов переводов, проверка CUDA/VRAM
и короткий измеренный GPU-прогон. GGUF из Ollama не является базой для QLoRA:
используется закреплённая исходная модель Safetensors и отдельный адаптер.
Этот архив не разрешает оплату, аренду или скачивание больших весов.
"""


def clean_code_revision():
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", *FILES], cwd=ROOT)
    if set(tracked.decode().strip("\0").split("\0")) != set(FILES):
        raise ValueError("Commit every transfer source file before pinning the archive")
    if subprocess.run(
        ["git", "diff", "HEAD", "--exit-code", "--", *FILES],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode:
        raise ValueError("Transfer source files differ from the pinned commit")
    return revision


def prepare(output, *, directory, review, native_audit, coverage, roles, encoder_report, tokenizer):
    output, directory, review = Path(output), Path(directory), Path(review)
    revision = clean_code_revision()
    manifest, parts = verify(directory)
    del parts
    review_manifest = json.loads((review / "manifest.json").read_text(encoding="utf-8"))
    if (
        review_manifest.get("status") != "OWNER_SAMPLE_REVIEW_PENDING"
        or review_manifest.get("rows") != 40
    ):
        raise ValueError("The preserved 40-row review packet is required")
    paths = {"tools/" + name: ROOT / name for name in FILES}
    for name, expected in review_manifest["files"].items():
        if Path(name).name != name or file_digest(review / name) != expected:
            raise ValueError("Original bilingual review packet changed")
        paths["review/" + name] = review / name
    paths["review/manifest.json"] = review / "manifest.json"
    for name in (
        "manifest.json",
        "train.jsonl.gz",
        "val.jsonl.gz",
        "test.jsonl.gz",
        "dispositions.jsonl.gz",
    ):
        paths["data/native/" + name] = directory / name
    for name, path in {
        "native-candidate-audit.json": native_audit,
        "source-domain-coverage.json": coverage,
        "raw-dm-role-extraction.json": roles,
        "actual-training-encoder.json": encoder_report,
    }.items():
        paths["audits/" + name] = Path(path)
    encoder = json.loads(Path(encoder_report).read_text(encoding="utf-8"))
    if (
        encoder.get("dataset_sha256") != manifest["sha256"]
        or encoder.get("actual_loss_masks_verified") != manifest["samples"]
        or encoder.get("status") != "STRUCTURAL_PASS_TRAINING_BLOCKED"
    ):
        raise ValueError("Complete actual encoder/mask report for this corpus is required")
    if file_digest(native_audit) != manifest["native_audit_sha256"]:
        raise ValueError("Native source audit differs")
    for name, expected in HASHES.items():
        path = Path(tokenizer) / name
        if file_digest(path) != expected:
            raise ValueError("Pinned tokenizer metadata changed")
        paths["assets/faun-tokenizer/" + name] = path
    if output.exists():
        raise FileExistsError("Preserve previous deliveries; choose a new output")
    hashes = {
        name: {"sha256": file_digest(path), "bytes": path.stat().st_size}
        for name, path in paths.items()
    }
    raw_guide = GUIDE.encode("utf-8")
    hashes["START_HERE_RU.md"] = {
        "sha256": hashlib.sha256(raw_guide).hexdigest(),
        "bytes": len(raw_guide),
    }
    result = {
        "schema": "gm-source-review-transfer-v1",
        "status": "RESEARCH_AND_OWNER_REVIEW_NOT_TRAIN_READY",
        "code_revision": revision,
        "dataset_sha256": manifest["sha256"],
        "native_samples": manifest["samples"],
        "bilingual_review_pairs": 40,
        "bilingual_complete": False,
        "human_reviewed": 0,
        "train_admitted": 0,
        "faun_weights_included": False,
        "raw_archive_included": False,
        "translation_weights_included": False,
        "training_steps": 0,
        "files": hashes,
    }
    with ZipFile(output, "x", ZIP_DEFLATED) as archive:
        for name, path in sorted(paths.items()):
            if shutil.disk_usage(output.parent).free < 194 * 1024**2:
                raise OSError("TRANSFER_FREE_SPACE_RESERVE_REACHED")
            archive.write(
                path, name, compress_type=ZIP_STORED if name.endswith(".gz") else ZIP_DEFLATED
            )
            if output.stat().st_size > 64 * 1024**2:
                raise OSError("TRANSFER_OUTPUT_BUDGET_REACHED")
        archive.writestr("START_HERE_RU.md", raw_guide)
        archive.writestr("transfer-manifest.json", json.dumps(result, indent=2))
    verify_archive(output)
    return result


def verify_archive(path):
    with ZipFile(path) as archive:
        entries = archive.infolist()
        names = [e.filename for e in entries]
        if (
            len(names) > 256
            or len(set(names)) != len(names)
            or sum(e.file_size for e in entries) > 128 * 1024**2
        ):
            raise ValueError("Duplicate archive members or archive size limit")
        for entry in entries:
            value = PurePosixPath(entry.filename)
            if (
                entry.orig_filename != entry.filename
                or value.is_absolute()
                or ".." in value.parts
                or "\\" in entry.filename
                or ":" in entry.filename
                or entry.filename.startswith("/")
                or (entry.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise ValueError("Unsafe transfer archive path")
        manifest = json.loads(archive.read("transfer-manifest.json"))
        if (
            manifest.get("schema") != "gm-source-review-transfer-v1"
            or manifest.get("status") != "RESEARCH_AND_OWNER_REVIEW_NOT_TRAIN_READY"
        ):
            raise ValueError("Unexpected transfer schema or admission status")
        if set(manifest["files"]) != set(names) - {"transfer-manifest.json"}:
            raise ValueError("Transfer inventory differs")
        for name, expected in manifest["files"].items():
            h, size = hashlib.sha256(), 0
            with archive.open(name) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(block)
                    size += len(block)
            if h.hexdigest() != expected["sha256"] or size != expected["bytes"]:
                raise ValueError("Transfer payload hash differs")
    return {
        "status": "ALL_TRANSFER_PAYLOAD_HASHES_VERIFIED_NOT_TRAIN_READY",
        "files": len(names) - 1,
        "archive_sha256": file_digest(path),
        "training_steps": 0,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("prepare")
    for name in (
        "output",
        "directory",
        "review",
        "native-audit",
        "coverage",
        "roles",
        "encoder-report",
        "tokenizer",
    ):
        b.add_argument("--" + name, type=Path, required=True)
    v = sub.add_parser("verify")
    v.add_argument("--archive", type=Path, required=True)
    a = p.parse_args()
    if a.command == "verify":
        result = verify_archive(a.archive)
    else:
        result = prepare(
            a.output,
            directory=a.directory,
            review=a.review,
            native_audit=a.native_audit,
            coverage=a.coverage,
            roles=a.roles,
            encoder_report=a.encoder_report,
            tokenizer=a.tokenizer,
        )
        result = {k: value for k, value in result.items() if k != "files"}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
