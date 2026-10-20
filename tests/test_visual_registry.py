"""Durable identity, immutable versions, atomic budgets and unknown billing outcomes."""

import sqlite3

import pytest

from rpg_vkr.visuals.registry import VisualRegistry


def test_versions_campaign_isolation_and_restart(tmp_path):
    r = VisualRegistry(tmp_path)
    for i in range(2):
        request = r.reserve("world:A", "npc:1", "model", 750000, 5000000)
        r.mark_submitted(request)
        asset = r.complete(request, b"image" + bytes([i]), refs=["old-id"], actual=700000)
    assert [a["version"] for a in r.versions("world:A", "npc:1")] == [2, 1]
    assert not r.versions("world:B", "npc:1")
    restored = VisualRegistry(tmp_path)
    assert restored.asset_path(asset).read_bytes() == b"image\x01"
    assert restored.totals()["actual"] == 1400000
    with pytest.raises(ValueError):
        restored.complete(request, b"duplicate")


def test_duplicate_inflight_and_cross_campaign_budget(tmp_path):
    r = VisualRegistry(tmp_path)
    a = r.reserve("A", "sword", "model", 750000, 1000000)
    with pytest.raises(ValueError):
        r.reserve("A", "sword", "model", 750000, 5000000)
    with pytest.raises(ValueError):
        r.reserve("B", "axe", "model", 750000, 1000000)
    r.mark_submitted(a)
    with pytest.raises(ValueError):
        r.mark_submitted(a)
    r.fail(a, "timeout")
    assert r.totals()["unknown"] == 1
    assert r.totals()["committed"] == 750000
    r.reconcile(a, 800000)
    assert r.totals()["committed"] == 800000


def test_crash_retains_submitted_reserve_but_releases_unsent(tmp_path):
    r = VisualRegistry(tmp_path)
    a = r.reserve("A", "npc", "m", 100, 1000)
    r.mark_submitted(a)
    r.reserve("A", "item", "m", 100, 1000)
    restored = VisualRegistry(tmp_path)
    statuses = {x["subject"]: x["status"] for x in restored.ledger()}
    assert statuses == {"npc": "uncertain", "item": "cancelled"}
    assert restored.totals()["committed"] == 100


def test_zero_budget_wrong_database_corruption_and_traversal(tmp_path):
    r = VisualRegistry(tmp_path / "valid")
    with pytest.raises(ValueError):
        r.reserve("A", "x", "m", 1, 0)
    with pytest.raises(ValueError):
        r.asset_path({"path": "../secret.png", "sha256": ""})
    folder = tmp_path / "foreign"
    folder.mkdir()
    with sqlite3.connect(folder / "visuals.sqlite3") as db:
        db.execute("CREATE TABLE evidence(x)")
    with pytest.raises(ValueError):
        VisualRegistry(folder)
