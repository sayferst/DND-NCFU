"""Local, resumable parallel-text preparation with explicit numeric and polarity diagnostics."""

import argparse
import gzip
import hashlib
import importlib.metadata
import json
import re
import shutil
import sqlite3
import time
from pathlib import Path

from training.fetch_translation_models import MODELS, digest
from training.fireball_observations import dumps
from training.source_gm_curation import clean_source_text, source_spans

VERSION = "gm-parallel-text-1"
TEXT_FIELDS = {
    "text",
    "player",
    "player_message",
    "name",
    "description",
    "weather",
    "class",
    "race",
    "effects",
    "before_utterances",
    "after_utterances",
    "utterance_history",
    "prior_dialogue",
    "preceding_utterances",
    "automation_results",
    "earlier_following_utterances",
    "earlier_same_source_utterance",
}
TERMS = {
    "saving throw": "спасбросок",
    "Saving Throw": "спасбросок",
    "Strength": "Сила",
    "Dexterity": "Ловкость",
    "Constitution": "Телосложение",
    "Intelligence": "Интеллект",
    "Wisdom": "Мудрость",
    "Charisma": "Харизма",
    "Fighter": "Воин",
    "Rogue": "Плут",
    "Wizard": "Волшебник",
    "Sorcerer": "Чародей",
    "Warlock": "Колдун",
    "Cleric": "Жрец",
    "Paladin": "Паладин",
    "Ranger": "Следопыт",
    "Bard": "Бард",
    "Druid": "Друид",
    "Monk": "Монах",
    "Barbarian": "Варвар",
    "Frightened": "Испуг",
    "Prone": "Лежит",
    "Unconscious": "Без сознания",
}


def key_for(text, direction):
    return hashlib.sha256(dumps([VERSION, direction, text]).encode()).hexdigest()


def fragments(text):
    text = clean_source_text(text)
    for left, right in source_spans(text, max_sentences=1):
        sentence = text[left:right]
        if len(sentence) <= 900:
            yield sentence
            continue
        part = ""
        for word in sentence.split():
            if part and len(part) + len(word) + 1 > 900:
                yield part
                part = ""
            part += (" " if part else "") + word
        if part:
            yield part


def human_strings(value, parent=None):
    if isinstance(value, str):
        if parent in TEXT_FIELDS and re.search(r"[A-Za-zА-Яа-яЁё]", value):
            yield value
    elif isinstance(value, list):
        for child in value:
            yield from human_strings(child, parent)
    elif isinstance(value, dict):
        for name, child in value.items():
            yield from human_strings(child, name)


def case_payload(case):
    if case["source"] == "PROJECT_REFERENCE":
        return json.loads(case["context"]["messages"][-1]["content"]), "ru-en"
    return case["context"], "en-ru"


def open_queue(path):
    db = sqlite3.connect(path, timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        "CREATE TABLE IF NOT EXISTS segments(id TEXT PRIMARY KEY,direction TEXT,"
        "source TEXT,target TEXT,back TEXT,status TEXT,qa TEXT)"
    )
    return db


def collect(cases, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    binding = {
        "version": VERSION,
        "cases_sha256": digest(Path(cases)),
        "models": MODELS,
        "terminology_sha256": hashlib.sha256(dumps(TERMS).encode()).hexdigest(),
    }
    job = output / "job.json"
    if job.exists() and json.loads(job.read_text(encoding="utf-8")) != json.loads(
        json.dumps(binding)
    ):
        raise ValueError("Changed parallel-text job; choose a new output")
    job.write_text(json.dumps(binding, indent=2) + "\n", encoding="utf-8")
    db = open_queue(output / "translations.sqlite")
    count = 0
    with gzip.open(cases, "rt", encoding="utf-8") as stream:
        for line in stream:
            case = json.loads(line)
            payload, direction = case_payload(case)
            for text in list(human_strings(payload)) + [case["target"]]:
                for fragment in fragments(text):
                    if re.fullmatch(r"(?:[A-Z_]+\d+|[A-Z]{1,4}|\d+)", fragment):
                        continue
                    db.execute(
                        "INSERT OR IGNORE INTO segments VALUES(?,?,?,NULL,NULL,'PENDING',NULL)",
                        (key_for(fragment, direction), direction, fragment),
                    )
            count += 1
            if count % 250 == 0:
                db.commit()
            if count % 5000 == 0:
                print(
                    dumps(
                        {
                            "cases_indexed_for_parallel_text": count,
                            "unique_segments": db.execute(
                                "SELECT COUNT(*) FROM segments"
                            ).fetchone()[0],
                        }
                    ),
                    flush=True,
                )
    db.commit()
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    report = {
        "cases": count,
        "segments": db.execute("SELECT COUNT(*) FROM segments").fetchone()[0],
        "directions": db.execute(
            "SELECT direction,COUNT(*) FROM segments GROUP BY direction"
        ).fetchall(),
    }
    db.close()
    (output / "queue.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def numbers(text):
    return re.findall(r"(?<!\w)\d+(?:[.,]\d+)?|(?<=\D)\d+", text)


def diagnostics(source, target, direction):
    issues = []
    if sorted(n.replace(",", ".") for n in numbers(source)) != sorted(
        n.replace(",", ".") for n in numbers(target)
    ):
        issues.append("NUMERIC_VALUES_DIFFER")
    if not target.strip():
        issues.append("EMPTY_TRANSLATION")
    if direction == "en-ru" and len(re.findall(r"[A-Za-z]", source)) >= 15:
        if not re.search(r"[А-Яа-яЁё]", target):
            issues.append("NO_RUSSIAN_TEXT")
    source_neg = (
        bool(re.search(r"\b(?:not|never|cannot|can't|without|unable)\b", source, re.I))
        if direction == "en-ru"
        else bool(re.search(r"\b(?:не|нет|нельзя|без|невозможно)\b", source, re.I))
    )
    target_neg = (
        bool(re.search(r"\b(?:не|нет|нельзя|без|невозможно|неспособ\w*)\b", target, re.I))
        if direction == "en-ru"
        else bool(re.search(r"\b(?:not|never|cannot|can't|without|unable)\b", target, re.I))
    )
    if source_neg and not target_neg:
        issues.append("NEGATION_REQUIRES_MEANING_REVIEW")
    return issues


def safe_batch(translator, texts, direction):
    """Quarantine an oversized fragment without aborting unrelated translations."""
    result, positions, admissible = [], [], []
    for i, text in enumerate(texts):
        if len(translator.source[direction].encode(text, out_type=str)) + 1 > 480:
            result.append((None, ["SOURCE_SEGMENT_EXCEEDS_MODEL_CONTEXT"]))
        else:
            result.append(None)
            positions.append(i)
            admissible.append(text)
    if admissible:
        for i, translated in zip(positions, translator.batch(admissible, direction), strict=True):
            result[i] = translated
    return result


class LocalTranslator:
    def __init__(self, root):
        import ctranslate2
        import sentencepiece

        for name, expected in (("ctranslate2", "4.8.5"), ("sentencepiece", "0.2.2")):
            if importlib.metadata.version(name) != expected:
                raise ValueError("Pinned translation runtime differs: " + name)
        root = Path(root)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.models, self.source, self.target = {}, {}, {}
        for direction, (repo, revision) in MODELS.items():
            ref = manifest["models"][direction]
            if (ref["repository"], ref["revision"]) != (repo, revision):
                raise ValueError("Unpinned local translation model")
            folder = root / direction
            for name, binding in ref["files"].items():
                if digest(folder / name) != binding["sha256"]:
                    raise ValueError("Local translation assets changed")
            self.models[direction] = ctranslate2.Translator(
                str(folder), device="cpu", compute_type="int8", intra_threads=2
            )
            self.source[direction] = sentencepiece.SentencePieceProcessor(
                model_file=str(folder / "source.spm")
            )
            self.target[direction] = sentencepiece.SentencePieceProcessor(
                model_file=str(folder / "target.spm")
            )

    def batch(self, texts, direction):
        tokens = [self.source[direction].encode(text, out_type=str) + ["</s>"] for text in texts]
        if any(len(row) > 480 for row in tokens):
            raise ValueError(
                "Translation source segment is too long; retain for segmentation review"
            )
        results = self.models[direction].translate_batch(
            tokens,
            beam_size=4,
            num_hypotheses=4,
            max_batch_size=2048,
            batch_type="tokens",
            max_decoding_length=512,
            return_end_token=True,
            max_input_length=0,
        )
        out = []
        for text, result in zip(texts, results, strict=True):
            candidates = []
            for hypothesis in result.hypotheses:
                complete = bool(hypothesis and hypothesis[-1] == "</s>")
                translated = self.target[direction].decode([t for t in hypothesis if t != "</s>"])
                if direction == "en-ru":
                    translated = re.sub(r"(\d+)\s+повреждени[яйе]", r"\1 урона", translated)
                    if text in TERMS:
                        translated = TERMS[text]
                issues = diagnostics(text, translated, direction)
                if not complete:
                    issues.append("DECODER_END_NOT_REACHED")
                candidates.append((len(issues), translated, issues))
            out.append(min(candidates, key=lambda row: row[0])[1:])
        return out


def run(output, model_root, *, limit=None):
    if limit is None or not 1 <= limit <= 320:
        raise ValueError(
            "Draft sentence translator requires a bounded --limit from 1 to 320; "
            "bulk training translation is disabled after observed meaning failures"
        )
    output = Path(output)
    if not (output / "translations.sqlite").is_file():
        raise FileNotFoundError(
            "Collect or restore the original translation queue before inference"
        )
    translator = LocalTranslator(model_root)
    db = open_queue(output / "translations.sqlite")
    processed, start = 0, time.monotonic()
    for direction in MODELS:
        while limit is None or processed < limit:
            rows = db.execute(
                "SELECT id,source FROM segments WHERE direction=? AND status='PENDING' "
                "ORDER BY id LIMIT 32",
                (direction,),
            ).fetchall()
            if not rows:
                break
            if limit is not None:
                rows = rows[: limit - processed]
            results = safe_batch(translator, [r[1] for r in rows], direction)
            back_direction = "ru-en" if direction == "en-ru" else "en-ru"
            backs = safe_batch(translator, [r[0] or "" for r in results], back_direction)
            for (key, source), (target, issues), (back, back_issues) in zip(
                rows, results, backs, strict=True
            ):
                qa = {
                    "issues": issues,
                    "back_issues": back_issues,
                    "back_is_diagnostic_not_meaning_proof": True,
                    "meaning_reviewed": False,
                    "human_reviewed": False,
                    "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "target_sha256": hashlib.sha256(target.encode()).hexdigest()
                    if target is not None
                    else None,
                }
                db.execute(
                    "UPDATE segments SET target=?,back=?,status=?,qa=? WHERE id=?",
                    (
                        target,
                        back,
                        "REVIEW_REQUIRED" if issues else "DRAFT_MEANING_REVIEW_REQUIRED",
                        dumps(qa),
                        key,
                    ),
                )
            db.commit()
            processed += len(rows)
            if processed % 320 == 0:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                if shutil.disk_usage(output).free < 192 * 1024**2:
                    raise OSError("TRANSLATION_FREE_SPACE_RESERVE_REACHED")
                print(
                    dumps(
                        {
                            "translated_segments": processed,
                            "direction": direction,
                            "elapsed_seconds": round(time.monotonic() - start, 1),
                            "states": db.execute(
                                "SELECT status,COUNT(*) FROM segments GROUP BY status"
                            ).fetchall(),
                        }
                    ),
                    flush=True,
                )
    states = db.execute("SELECT status,COUNT(*) FROM segments GROUP BY status").fetchall()
    db.close()
    return {"processed": processed, "states": states, "training_steps": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--collect", type=Path)
    parser.add_argument("--models", type=Path)
    parser.add_argument("--limit", type=int, help="Required for draft inference: 1..320 segments")
    args = parser.parse_args()
    if args.collect:
        print(json.dumps(collect(args.collect, args.output), indent=2))
    if args.models:
        print(json.dumps(run(args.output, args.models, limit=args.limit), indent=2))


if __name__ == "__main__":
    main()
