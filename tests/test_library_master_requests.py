"""Validated model IDs resolve into actual engine registrations and real UI transactions."""

from copy import deepcopy

import pytest
from test_library_utility_runtime import library  # noqa: F401
from test_owner_rules_runtime import campaign

from rpg_vkr.application import Session
from rpg_vkr.world_library.bridge import commit
from rpg_vkr.world_library.model import digest
from rpg_vkr.world_library.narrator import retrieve
from rpg_vkr.world_library.requests import prepare, validate_requests


def request(library, id="wl_weapon_0_0"):  # noqa: F811
    return {
        "template_id": id,
        "instance_id": "requested_item",
        "revision": library.revision(id),
        "digest": digest(library.get(id)),
        "with_inventory": False,
    }


def test_proposal_is_inert_then_engine_commits_exact_template(library):  # noqa: F811
    s = campaign(hp=12)
    proposal = request(library)
    before, rng = s.to_dict(), s.dice.checkpoint()
    record = prepare(s, [proposal], path=library.db.execute("PRAGMA database_list").fetchone()[2])
    assert s.to_dict() == before and s.dice.checkpoint() == rng
    commit(s, record)
    actual = next(e for e in s.catalog.entities if e.id == "requested_item")
    assert actual.definition_id == proposal["template_id"] and not actual.owner_id
    assert s.dice.checkpoint() == rng
    assert Session.from_dict(s.to_dict(), version=31).to_dict() == s.to_dict()


def test_stale_digest_and_arbitrary_hp_are_rejected(library):  # noqa: F811
    path = library.db.execute("PRAGMA database_list").fetchone()[2]
    context = retrieve("wl_weapon_0_0", path=path)
    proposal = request(library)
    validate_requests([proposal], context)
    bad = deepcopy(proposal) | {"hp": 999}
    with pytest.raises(ValueError):
        validate_requests([bad], context)
    bad = proposal | {"digest": "0" * 64}
    with pytest.raises(ValueError, match="Stale"):
        prepare(campaign(hp=12), [bad], path=path)


def test_existing_world_entity_and_missing_template_are_not_overwritten(library):  # noqa: F811
    s = campaign(hp=12)
    path = library.db.execute("PRAGMA database_list").fetchone()[2]
    before, rng = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError):
        prepare(s, [request(library) | {"instance_id": "wounded"}], path=path)
    assert s.to_dict() == before and s.dice.checkpoint() == rng


def test_concurrent_catalog_update_cannot_mix_template_revisions(
    library,  # noqa: F811
    monkeypatch,
):
    from rpg_vkr.world_library.store import Library

    library.execute("PRAGMA journal_mode=WAL")
    path = library.db.execute("PRAGMA database_list").fetchone()[2]
    proposal = request(library)
    original = library.get(proposal["template_id"])
    reader_get, updated = Library.get, False

    def update_between_reads(reader, id, revision=None):
        nonlocal updated
        row = reader_get(reader, id, revision)
        if reader is not library and not updated:
            updated = True
            changed = deepcopy(original)
            changed["description"] += " Новая редакция во время чтения."
            library.import_records([changed], expected={original["id"]: 1})
        return row

    monkeypatch.setattr(Library, "get", update_between_reads)
    s = campaign(hp=12)
    before, rng = s.to_dict(), s.dice.checkpoint()
    record = prepare(s, [proposal], path=path)
    selected = next(d for d in record.definitions if d.id == original["id"])
    assert selected.properties["library_revision"] == 1
    assert selected.properties["library_digest"] == proposal["digest"]
    assert selected.properties["description"] == original["description"]
    assert library.revision(original["id"]) == 2
    assert s.to_dict() == before and s.dice.checkpoint() == rng


def test_actual_master_chat_creates_a_pinned_instance_after_confirmation(
    library,  # noqa: F811
    window,
    qt_app,
    monkeypatch,
):
    from test_catalog_ui import enable, send
    from test_routerai import router_server

    path = library.db.execute("PRAGMA database_list").fetchone()[2]
    monkeypatch.setenv("RPG_VKR_WORLD_LIBRARY", path)
    window._session = s = campaign(hp=12)
    monkeypatch.setattr(window, "_confirm", lambda _: True)
    text = "Создай рядом wl_weapon_0_0"
    proposal = {
        "steps": [],
        "places": [],
        "check": "none",
        "library_requests": [request(library)],
    }
    with router_server(
        world_plans={text: proposal},
        writer_text=(
            "На земле у переправы лежит короткий меч. На рукояти заметно клеймо мастерской."
        ),
    ) as (url, records):
        enable(window, monkeypatch, url)
        send(window, qt_app, text)
        assert any(e.id == "requested_item" for e in s.catalog.entities)
        assert not any(
            e.owner_id == "hero" and e.id == "requested_item" for e in s.catalog.entities
        )
        assert records


@pytest.mark.parametrize("value", [None, "", {}, 0, False])
def test_false_non_list_requests_are_rejected(value):
    with pytest.raises(ValueError):
        validate_requests(value, None)


@pytest.mark.parametrize("mode", ["decline", "reply", "malformed"])
def test_master_chat_never_applies_declined_or_invalid_creation(
    library,  # noqa: F811
    window,
    qt_app,
    monkeypatch,
    mode,
):
    from test_catalog_ui import enable, send
    from test_routerai import router_server

    monkeypatch.setenv(
        "RPG_VKR_WORLD_LIBRARY", library.db.execute("PRAGMA database_list").fetchone()[2]
    )
    window._session = s = campaign(hp=12)
    monkeypatch.setattr(window, "_confirm", lambda _: False)
    text = "Создай рядом wl_weapon_0_0"
    proposal = {"steps": [], "places": [], "check": "none", "library_requests": [request(library)]}
    if mode == "reply":
        proposal["reply"] = "Меч уже у тебя, характеристики изменены."
    elif mode == "malformed":
        proposal["library_requests"] = 0
    old_catalog, old_rng = s.catalog, s.dice.checkpoint()
    with router_server(world_plans={text: proposal}) as (url, _):
        enable(window, monkeypatch, url)
        send(window, qt_app, text)
        assert s.catalog == old_catalog
        assert s.dice.checkpoint() == old_rng
