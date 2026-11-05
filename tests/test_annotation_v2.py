from collections import Counter
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from training.annotation_v2 import export, import_review, rows_v2
from training.scenarios import candidates
from training.xlsx import NS, read


def alter(source, output, changes):
    with ZipFile(source) as src, ZipFile(output, "x") as dst:
        for name in src.namelist():
            raw = src.read(name)
            if name in changes:
                root = ET.fromstring(raw)
                for address, value in changes[name].items():
                    cell = next(c for c in root.iter("{" + NS + "}c") if c.attrib["r"] == address)
                    for child in list(cell):
                        cell.remove(child)
                    cell.set("t", "inlineStr")
                    ET.SubElement(
                        ET.SubElement(cell, "{" + NS + "}is"), "{" + NS + "}t"
                    ).text = value
                raw = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            dst.writestr(name, raw)


def test_balanced_sampling_keeps_ids_and_spans_all_conditions():
    rows = rows_v2()
    selected = [r for r in rows if r["review_track"] == "HUMAN_FIRST"]
    assert {r["id"] for r in rows} == {r["id"] for r in candidates()}
    assert Counter(r["condition_type"] for r in selected) == dict.fromkeys(range(5), 40)
    assert set(Counter(r["family"] for r in selected).values()) == {10}
    assert len({r["action"] for r in selected}) == 200


def test_partial_labels_and_second_sheet_are_imported_separately(tmp_path):
    path = tmp_path / "v2.xlsx"
    export(path)
    edited = tmp_path / "edited.xlsx"
    alter(
        path,
        edited,
        {
            "xl/worksheets/sheet1.xml": {"G2": "Да"},
            "xl/worksheets/sheet2.xml": {
                "E3": "Тетива снята, лук больше не оружие.",
                "F3": "-",
                "G3": "Факты мира",
                "H3": "Ответ ошибся в исходе.",
                "I3": "Сохранена заготовка снасти.",
            },
        },
    )
    result = import_review(edited, tmp_path / "corpora")
    assert result["counts"] == {
        "action_labels": 1,
        "narrator_reviews": 1,
        "verified_episodes": 0,
        "math_conflicts": 4,
    }
    assert result["sft_admitted"] == 0
    assert "UNLABELED" in (tmp_path / "corpora/narrator_reviews.jsonl").read_text(encoding="utf-8")


def test_cross_sheet_rating_conflict_and_fact_tampering_fail_without_output(tmp_path):
    path = tmp_path / "v2.xlsx"
    export(path)
    for name, changes in [
        (
            "conflict",
            {"xl/worksheets/sheet1.xml": {"N2": "+"}, "xl/worksheets/sheet2.xml": {"F2": "-"}},
        ),
        ("facts", {"xl/worksheets/sheet2.xml": {"B2": "Подмена контекста"}}),
        ("approval", {"xl/worksheets/sheet2.xml": {"L2": "Одобрено человеком"}}),
    ]:
        edited = tmp_path / (name + ".xlsx")
        alter(path, edited, changes)
        with pytest.raises(ValueError):
            import_review(edited, tmp_path / name)
        assert not (tmp_path / name).exists()


def test_examples_are_not_counted_as_owner_labels_and_v1_is_preserved(tmp_path):
    from training.annotation import export_workbook

    old = tmp_path / "v1.xlsx"
    export_workbook(old)
    before = old.read_bytes()
    new = tmp_path / "v2.xlsx"
    export(new, carry_from=old)
    assert old.read_bytes() == before
    assert len(read(new, sheet="Примеры разметки")) == 21
    assert len(read(new, sheet="Архив v1 лист 1")) == 1001
    result = import_review(new, tmp_path / "blank")
    assert result["counts"]["narrator_reviews"] == result["counts"]["action_labels"] == 0


@pytest.mark.parametrize("problem", ("duplicate", "missing", "formula", "fake_approval"))
def test_v2_import_rejects_corrupted_ids_formulas_and_approval(tmp_path, problem):
    path = tmp_path / "v2.xlsx"
    export(path)
    edited = tmp_path / "corrupt.xlsx"
    with ZipFile(path) as src, ZipFile(edited, "x") as dst:
        for name in src.namelist():
            raw = src.read(name)
            if name == "xl/worksheets/sheet2.xml":
                root = ET.fromstring(raw)
                cells = {c.attrib["r"]: c for c in root.iter("{" + NS + "}c")}
                if problem in ("duplicate", "missing"):
                    text = cells["A3"].find(".//{" + NS + "}t")
                    text.text = (
                        read(path, sheet="Ответы мастера")[1]["A"] if problem == "duplicate" else ""
                    )
                elif problem == "formula":
                    ET.SubElement(
                        cells["I2"], "{" + NS + "}f"
                    ).text = 'HYPERLINK("https://invalid")'
                else:
                    cells["L2"].find(".//{" + NS + "}t").text = "Допущено в обучение"
                raw = ET.tostring(root)
            dst.writestr(name, raw)
    with pytest.raises(ValueError):
        import_review(edited, tmp_path / "output", reviewer="owner", confirm_human=True)
    assert not (tmp_path / "output").exists()


def test_action_approval_does_not_approve_an_answer_on_the_other_sheet(tmp_path):
    path, edited = tmp_path / "v2.xlsx", tmp_path / "reviewed.xlsx"
    export(path)
    alter(
        path,
        edited,
        {
            "xl/worksheets/sheet1.xml": {
                "G2": "Да",
                "H2": "Частично",
                "I2": "Да",
                "Q2": "Одобрено человеком",
                "R2": "owner",
            },
            "xl/worksheets/sheet2.xml": {"E2": "Лук разобран.", "F2": "−"},
        },
    )
    folder = tmp_path / "output"
    import_review(edited, folder, reviewer="owner", confirm_human=True)
    import json

    action = json.loads((folder / "action_labels.jsonl").read_text(encoding="utf-8"))
    answer = json.loads((folder / "narrator_reviews.jsonl").read_text(encoding="utf-8"))
    assert action["review_status"] == "HUMAN_APPROVED"
    assert answer["review_status"] == "UNLABELED" and answer["rating"] == "-"


def test_v1_manual_action_score_is_archived_without_becoming_a_narrator_score(tmp_path):
    from training.annotation import export_workbook

    old, edited, new = (tmp_path / name for name in ("v1.xlsx", "reviewed.xlsx", "v2.xlsx"))
    export_workbook(old)
    alter(
        old, edited, {"xl/worksheets/sheet1.xml": {"G2": "YES", "N2": "+", "O2": "Мой комментарий"}}
    )
    before = edited.read_bytes()
    export(new, carry_from=edited)
    assert edited.read_bytes() == before
    assert read(new, sheet="Архив v1 лист 1")[1]["O"] == "Мой комментарий"
    row = read(new, sheet="Действия игроков")[1]
    assert row["G"] == "Да" and row["N"] == ""
    assert "Оценка действия v1: +" in row["K"]


def test_conflict_comments_are_preserved_without_inferred_human_approval(tmp_path):
    import json

    path, edited = tmp_path / "v2.xlsx", tmp_path / "notes.xlsx"
    export(path)
    alter(path, edited, {"xl/worksheets/sheet3.xml": {"I2": "+", "J2": "Проверить веса жителей"}})
    folder = tmp_path / "output"
    import_review(edited, folder)
    rows = [
        json.loads(line)
        for line in (folder / "math_conflicts.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["review"]["comment"] == "Проверить веса жителей"
    assert rows[0]["review"]["rating"] == "+" and rows[0]["human_approved"] is False


def test_excel_saved_empty_inline_cells_are_valid_partial_annotations(tmp_path):
    path, edited = tmp_path / "v2.xlsx", tmp_path / "empty-cells.xlsx"
    export(path)
    with ZipFile(path) as src, ZipFile(edited, "x") as dst:
        for name in src.namelist():
            raw = src.read(name)
            if name == "xl/worksheets/sheet2.xml":
                root = ET.fromstring(raw)
                for cell in root.iter("{" + NS + "}c"):
                    if cell.attrib["r"] in ("E2", "F2", "I2"):
                        for child in list(cell):
                            cell.remove(child)
                raw = ET.tostring(root)
            dst.writestr(name, raw)
    report = import_review(edited, tmp_path / "corpora")
    assert report["counts"]["narrator_reviews"] == 0
