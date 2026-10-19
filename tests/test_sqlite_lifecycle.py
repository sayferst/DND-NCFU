"""File handles must close before replacement/cleanup, even when GC is delayed."""

import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from rpg_vkr.application import Session
from rpg_vkr.storage.catalog import CatalogIndex
from rpg_vkr.storage.knowledge import CampaignIndex, restore_session


@pytest.fixture
def file_connections(monkeypatch):
    connect = sqlite3.connect
    retained = []

    def retain(database, *args, **kwargs):
        db = connect(database, *args, **kwargs)
        if str(database) != ":memory:":
            retained.append(db)
        return db

    # Real connections are kept alive so collection cannot hide missing close().
    monkeypatch.setattr(sqlite3, "connect", retain)
    yield retained
    for db in retained:
        db.close()


def assert_closed(connections):
    assert connections
    for db in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            db.execute("SELECT 1")


def test_publish_closes_temporary_and_previous_database_before_replace(
    tmp_path, monkeypatch, file_connections
):
    from rpg_vkr.storage import catalog

    replace = catalog.os.replace
    replacements = []

    def require_closed(source, destination):
        assert_closed(file_connections)
        replacements.append(destination)
        return replace(source, destination)

    monkeypatch.setattr(catalog.os, "replace", require_closed)
    path = tmp_path / "working.sqlite3"
    index = CatalogIndex(Session(seed=5))
    try:
        index.publish(path)
        index.publish(path)
        assert replacements == [path, path]
        assert_closed(file_connections)
        assert restore_session(path).to_dict() == index.session.to_dict()
        assert_closed(file_connections)
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        index.close()


@pytest.mark.parametrize("index_type", [CatalogIndex, CampaignIndex])
def test_export_closes_database_before_return(tmp_path, file_connections, index_type):
    session = Session(seed=5)
    index = index_type(session)
    try:
        path = tmp_path / "export.sqlite3"
        index.export(path)
        assert_closed(file_connections)
        assert restore_session(path).to_dict() == session.to_dict()
        assert_closed(file_connections)
    finally:
        index.close()


@pytest.mark.parametrize("valid", [True, False], ids=["valid", "invalid"])
def test_restore_closes_database_on_success_and_invalid_snapshot(tmp_path, file_connections, valid):
    path = tmp_path / "campaign.sqlite3"
    index = CampaignIndex(Session(seed=5))
    try:
        index.export(path)
    finally:
        index.close()
    if not valid:
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("DELETE FROM snapshot")
        with pytest.raises(ValueError, match="Invalid campaign snapshot"):
            restore_session(path)
    else:
        restore_session(path)
    assert_closed(file_connections)


@pytest.mark.parametrize(
    ("index_type", "operation"),
    [(CatalogIndex, "export"), (CampaignIndex, "export"), (CatalogIndex, "publish")],
)
def test_failed_backup_closes_before_cleanup_and_preserves_error(
    tmp_path, monkeypatch, file_connections, index_type, operation
):
    index = index_type(Session(seed=5))
    original = index.db
    path = tmp_path / "output.sqlite3"
    unlink = type(path).unlink

    def fail(target):
        target.execute("CREATE TABLE partial(value TEXT)")
        raise OSError("backup interrupted")

    def require_closed(self, *args, **kwargs):
        assert_closed(file_connections)
        return unlink(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "unlink", require_closed)
    index.db = SimpleNamespace(backup=fail)
    try:
        with pytest.raises(OSError, match="backup interrupted"):
            getattr(index, operation)(path)
        assert_closed(file_connections)
        assert not path.exists()
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        index.db = original
        index.close()


def test_foreign_database_check_closes_read_handle_and_preserves_bytes(tmp_path, file_connections):
    path = tmp_path / "foreign.sqlite3"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE keep_me(value TEXT)")
    before = path.read_bytes()
    index = CatalogIndex(Session(seed=5))
    try:
        with pytest.raises(ValueError, match="другая база"):
            index.publish(path)
        assert_closed(file_connections)
        assert path.read_bytes() == before
    finally:
        index.close()
