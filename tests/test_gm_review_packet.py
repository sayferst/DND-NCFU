"""Blank packets, corrections and source samples cannot silently approve a whole corpus."""

import gzip
import json

import pytest

from training.gm_review_packet import build, import_review, rows_for
from training.xlsx import write


def packet(tmp_path):
    case = {
        "id": "one",
        "source": "FIREBALL",
        "split": "train",
        "source_unit": "raw:10",
        "context": {"task": "continue_dm_scene", "history": [{"text": "I knock."}]},
        "target": 'The guard asks, "What do you need?"',
        "provenance": {"source_language": "en"},
    }
    edit = {
        "case_id": "one",
        "reply_en": case["target"],
        "reply_ru": "Стражник спрашивает: «Что тебе нужно?»",
        "scene_en": "A traveler knocks.",
        "scene_ru": "Путник стучит.",
        "review_note": "Проверить ответ NPC.",
    }
    cases, edits = tmp_path / "cases.gz", tmp_path / "edits.json"
    with gzip.open(cases, "wt", encoding="utf-8") as f:
        f.write(json.dumps(case) + "\n")
    edits.write_text(json.dumps([edit], ensure_ascii=False), encoding="utf-8")
    root = tmp_path / "packet"
    build(cases, edits, root, expected_rows=1)
    return root, case, edit


def returned(root, path, **columns):
    cases = [
        json.loads(line)
        for line in (root / "review-cases.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    rows = rows_for(cases)
    for index, value in columns.items():
        rows[1][int(index)] = value
    write(path, [("40 примеров", rows, {})])


def test_blank_workbook_is_not_a_human_review(tmp_path):
    root, _, _ = packet(tmp_path)
    result = import_review(root, root / "DND_NCFU_REVIEW_40_RU_EN.xlsx", tmp_path / "labels.json")
    assert result["reviewed_rows"] == 0 and result["unreviewed_rows"] == 1
    assert result["whole_corpus_approved"] is False and result["training_steps"] == 0


def test_owner_labels_apply_only_to_the_actual_reviewed_source_row(tmp_path):
    root, _, _ = packet(tmp_path)
    edited = tmp_path / "returned.xlsx"
    returned(
        root, edited, **{"8": "5", "9": "Да", "10": "4", "11": "Да", "12": "Одобрено человеком"}
    )
    result = import_review(root, edited, tmp_path / "labels.json")
    assert result["reviewed_rows"] == 1
    assert result["labels"][0]["case_id"] == "one"
    assert result["labels"][0]["train_admitted"] is False
    assert result["whole_corpus_approved"] is False


def test_changing_prepared_source_or_translation_is_detected(tmp_path):
    root, _, _ = packet(tmp_path)
    edited = tmp_path / "returned.xlsx"
    returned(root, edited, **{"5": "NEW_FACT_NOT_IN_SOURCE"})
    with pytest.raises(ValueError, match="versions changed"):
        import_review(root, edited, tmp_path / "labels.json")


def test_proposed_correction_requires_revalidation_even_if_marked_approved(tmp_path):
    root, _, _ = packet(tmp_path)
    edited = tmp_path / "returned.xlsx"
    returned(
        root,
        edited,
        **{
            "8": "5",
            "9": "Да",
            "10": "5",
            "11": "Да",
            "12": "Одобрено человеком",
            "13": "Другой ответ.",
        },
    )
    with pytest.raises(ValueError, match="unverified correction"):
        import_review(root, edited, tmp_path / "labels.json")


def test_holdout_and_source_rewrite_cannot_enter_style_review(tmp_path):
    root, case, edit = packet(tmp_path)
    source = tmp_path / "other.gz"
    with gzip.open(source, "wt", encoding="utf-8") as f:
        f.write(json.dumps(case | {"split": "test"}) + "\n")
    with pytest.raises(ValueError, match="validation/test"):
        build(source, tmp_path / "edits.json", tmp_path / "bad-holdout", expected_rows=1)
    edit["reply_en"] = "An invented original response."
    (tmp_path / "rewritten.json").write_text(json.dumps([edit]), encoding="utf-8")
    with pytest.raises(ValueError, match="verbatim"):
        build(
            tmp_path / "cases.gz",
            tmp_path / "rewritten.json",
            tmp_path / "bad-source",
            expected_rows=1,
        )


def test_partial_label_without_explicit_decision_is_not_an_approval(tmp_path):
    root, _, _ = packet(tmp_path)
    edited = tmp_path / "returned.xlsx"
    returned(root, edited, **{"8": "5"})
    with pytest.raises(ValueError, match="explicit decision"):
        import_review(root, edited, tmp_path / "labels.json")
