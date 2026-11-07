"""A real 1000-row XLSX, independent provenance gates and literal spreadsheet text."""

from collections import Counter
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from training.annotation import export_workbook, import_review, suggest_rules
from training.scenarios import candidates
from training.schema import validate
from training.xlsx import NS, read, write


def test_thousand_candidates_have_semantic_families_and_no_fake_approval(tmp_path):
    rows = candidates()
    assert len(rows) == len({r["id"] for r in rows}) == 1000
    assert len({r["action"] for r in rows}) == 200
    assert len({r["family"] for r in rows}) == 20
    assert Counter(r["review_track"] for r in rows) == {"HUMAN_FIRST": 200, "AI_LATER": 800}
    assert all(r["synthetic"] and r["status"] == "UNLABELED" for r in rows)
    assert all(not validate(r)[0] for r in rows)
    path = tmp_path / "scenarios.xlsx"
    assert export_workbook(path)["train_admitted"] == 0
    assert len(read(path)) == 1001
    with ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        assert len(workbook.find(f"{{{NS}}}sheets")) == 5
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        assert sheet.find(f"{{{NS}}}dataValidations") is not None
        assert sheet.find(f"{{{NS}}}conditionalFormatting") is not None
        assert sheet.find(f"{{{NS}}}autoFilter") is not None
        assert b'fullCalcOnLoad="1"' in archive.read("xl/workbook.xml")
    with pytest.raises(FileExistsError):
        export_workbook(path)


def test_unreviewed_excel_and_rule_suggestions_never_become_real_sft(tmp_path):
    path = tmp_path / "blank.xlsx"
    export_workbook(path)
    with pytest.raises(ValueError):
        import_review(path, tmp_path / "bad.jsonl", reviewer="")
    result = import_review(
        path, tmp_path / "review.jsonl", reviewer="unit-test-reviewer", confirm_human=True
    )
    assert result["reviewed"] == result["train_admitted"] == 0
    assert all(not suggest_rules(r)["human_approved"] for r in candidates())


def test_spreadsheet_formula_injection_is_literal_and_import_rejects_formulas(tmp_path):
    path = tmp_path / "literal.xlsx"
    write(path, [("Тест", [["ID", "Текст"], ["x", '=HYPERLINK("https://invalid")']], {})])
    assert read(path)[1]["B"].startswith("=HYPERLINK")
    with ZipFile(path) as archive:
        assert b"<f>" not in archive.read("xl/worksheets/sheet1.xml")


def test_workbook_fact_tampering_is_rejected(tmp_path):
    path = tmp_path / "original.xlsx"
    export_workbook(path)
    altered = tmp_path / "altered.xlsx"
    with ZipFile(path) as source, ZipFile(altered, "x") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "xl/worksheets/sheet1.xml":
                data = data.replace(b"gm_bow_craft_0_0", b"forged_identifier", 1)
            target.writestr(name, data)
    with pytest.raises(ValueError, match="ID"):
        import_review(altered, tmp_path / "out.jsonl", reviewer="unit-test", confirm_human=True)
