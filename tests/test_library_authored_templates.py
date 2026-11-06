"""New model-authored templates have real handlers, traceable origin and reviewed ownership."""

import json
from copy import deepcopy

import pytest
from test_library_utility_runtime import library  # noqa: F401
from test_owner_rules_runtime import campaign

from rpg_vkr.application import Session
from rpg_vkr.world_library.bridge import commit, preview
from rpg_vkr.world_library.proposal_policy import prepare_record


def draft(catalog, profile, name):
    row = deepcopy(next(r for r in catalog.all() if r["profile"] == profile))
    row.pop("id")
    row.pop("provenance")
    row["name"] = name
    return row


def test_documented_example_and_optional_generated_id_match_the_published_schema():
    from rpg_vkr.world_library.model import ROOT, schemas, validate

    value = json.loads(
        (ROOT / "data/world_library/examples/authored-npc.json").read_text(encoding="utf-8")
    )
    validate(value, schemas()["authored_proposal"])
    record = prepare_record(
        value["record"], model=value["model"], prompt_version=value["prompt_version"]
    )
    assert record["id"].startswith("gm_")


def test_authored_npc_stats_trade_and_social_contract_do_not_depend_on_generator_name(
    library,  # noqa: F811
):
    row = draft(library, "npc", "Ремзий: новый мастер-алхимик")
    row["attributes"].update(profession="мастер-алхимик", can_trade=True)
    original = deepcopy(row)
    record = prepare_record(row, model="test-local-model", prompt_version="npc-author-1")
    assert (
        row == original
        and record["id"]
        == prepare_record(row, model="test-local-model", prompt_version="npc-author-1")["id"]
    )
    assert record["provenance"]["origin"] == "invented/homebrew"
    assert record["provenance"]["review"] == "unreviewed"
    id = library.propose_authored(row, model="test-local-model", prompt_version="npc-author-1")
    assert library.proposal(id)["status"] == "pending"
    with pytest.raises(KeyError):
        library.get(record["id"])
    library.approve(id, actor="human-reviewer")
    s = campaign(hp=12)
    rng = s.dice.checkpoint()
    commit(s, preview(library, s, record["id"], "new_alchemist", with_inventory=True))
    definition = next(d for d in s.catalog.definitions if d.id == record["id"])
    assert definition.properties["can_trade"]
    assert definition.properties["library_social_rules"]["version"] == "library-social-1"
    assert definition.properties["strength"] == row["attributes"]["abilities"]["strength"]
    assert any(e.owner_id == "new_alchemist" for e in s.catalog.entities)
    assert s.dice.checkpoint() == rng
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()


def test_authored_medicine_with_a_new_generator_really_heals_and_replays(library):  # noqa: F811
    row = draft(library, "medicine", "Состав травника: новый лечебный образец")
    row["provenance"] = {
        "origin": "invented/homebrew",
        "source": "Original fantasy design",
        "generator": "my-local-model-17",
        "review": "engineer-reviewed",
    }
    id = library.propose_authored(row, model="test-local-model", prompt_version="medicine-author-1")
    record = library.proposal(id)["record"]
    library.approve(id, actor="human-reviewer")
    assert record["provenance"]["generator"] == "my-local-model-17"
    assert record["provenance"]["review"] == "unreviewed"
    s = campaign(hp=2)
    commit(s, preview(library, s, record["id"], "authored_medicine"))
    s.perform_gameplay(
        "attempt",
        {
            "version": 1,
            "plan": {
                "operation": "take",
                "goal": "",
                "items": ["authored_medicine"],
                "tool": "",
            },
        },
        "take-new-medicine",
    )
    s.perform_gameplay(
        "library_use", {"item": "authored_medicine", "target": "wounded"}, "use-new-medicine"
    )
    actor = next(e for e in s.catalog.entities if e.id == "wounded")
    assert actor.state["hp"] > 2
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()


def test_new_authoring_rejects_missing_stats_unknown_callbacks_and_unresolved_species(
    library,  # noqa: F811
):
    row = draft(library, "npc", "Некорректный новый персонаж")
    incomplete = deepcopy(row)
    incomplete["attributes"].pop("abilities")
    with pytest.raises(ValueError, match="abilities"):
        library.propose_authored(incomplete, model="test", prompt_version="v1")
    unknown = deepcopy(row)
    unknown["attributes"]["mood_transitions"] = [
        {"from": "wary", "to": "calm", "event": "story says so"}
    ]
    with pytest.raises(ValueError, match="verified engine"):
        library.propose_authored(unknown, model="test", prompt_version="v1")
    mismatch = deepcopy(row)
    mismatch["attributes"]["species"] = "wl_missing_species"
    with pytest.raises(ValueError, match="species"):
        library.propose_authored(mismatch, model="test", prompt_version="v1")


@pytest.mark.parametrize("accept", [True, False])
def test_real_ui_shows_reviewed_data_and_records_acceptance_or_rejection(
    library,  # noqa: F811
    qt_app,
    tmp_path,
    monkeypatch,
    accept,
):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from rpg_vkr.world_library.ui import LibraryWindow

    row = draft(library, "material", f"Авторский образец для проверки интерфейса {accept}")
    row["description"] = 'Оригинальное описание. <img src="file:///private.png">'
    path = tmp_path / "authored.json"
    path.write_text(
        json.dumps(
            {"record": row, "model": "test-local-model", "prompt_version": "ui-author-1"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    shown = []

    def decide(*args, **kwargs):
        shown.append(args[2])
        assert row["name"] in args[2] and "<img" not in args[2] and "&lt;img" in args[2]
        assert args[-1] == QMessageBox.StandardButton.No
        return QMessageBox.StandardButton.Yes if accept else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", decide)
    window = LibraryWindow(library)
    try:
        window.propose_file()
    finally:
        window.close()
    record = prepare_record(row, model="test-local-model", prompt_version="ui-author-1")
    assert shown and bool(library.revision(record["id"])) == accept
    raw = library.execute("SELECT status,payload FROM wl_proposals").fetchall()
    match = next(
        (status, library._decode(payload))
        for status, payload in raw
        if library._decode(payload)["record"]["id"] == record["id"]
    )
    assert match[0] == ("approved" if accept else "rejected")
