"""All literal declarations are visited without evaluating source JavaScript."""

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/import_rpgd100_facts.py"
spec = importlib.util.spec_from_file_location("source_literal_bindings_test", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_comma_declarations_and_frozen_literals_are_not_lost():
    rows = list(
        module.literal_bindings(
            'const firearmsData=[{name:"A",damage:"1к6"}],'
            'explosivesData=[{name:"B",weight:"1 фнт."}];'
            'let armor=Object.freeze([{name:"C",ac:12}]);'
        )
    )
    assert [r[0]["name"] for r in rows] == ["A", "B", "C"]


def test_executable_expression_is_never_evaluated(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    marker = tmp_path / "never-created"
    source = 'const a=[{name: require("fs").writeFileSync("' + marker.as_posix() + '","bad")}];'
    assert list(module.literal_bindings(source)) == []
    assert not marker.exists()
