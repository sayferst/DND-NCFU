"""Approval, rejection and the template/audit writes form a single durable transaction."""

import os
import uuid
from copy import deepcopy

import pytest

from rpg_vkr.world_library.model import ROOT, digest, dump, read_jsonl
from rpg_vkr.world_library.store import Library


@pytest.fixture(params=["sqlite", "postgres"])
def proposals_db(request, tmp_path):
    if request.param == "sqlite":
        library = Library.sqlite(tmp_path / "proposals.sqlite3")
        library.migrate()
        try:
            yield library
        finally:
            library.close()
        return
    dsn = os.environ.get("DND_LIBRARY_TEST_DSN")
    if not dsn:
        pytest.skip("Dedicated PostgreSQL test DSN not configured")
    import psycopg
    from psycopg import sql

    schema = "proposal_test_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        library = Library.postgres(dsn)
        library.db.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        try:
            library.migrate()
            yield library
        finally:
            library.close()
            # Only the unique schema created above belongs to this test.
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture(scope="module")
def proposed_record():
    row = deepcopy(read_jsonl(ROOT / "data/world_library/seed-v1.jsonl")[0])
    row.update(id="wl_atomic_proposal", name="Проверенный образец материала")
    return row


def pending(library, row):
    return library.propose(row, model="offline-test-model", prompt_version="test-proposal-1")


def status(library, id):
    return library.execute("SELECT status FROM wl_proposals WHERE id=?", (id,)).fetchone()[0]


def test_sqlite_failed_commit_rolls_back_the_entire_approval(tmp_path, proposed_record):
    library = Library.sqlite(tmp_path / "failed-commit.sqlite3")
    try:
        library.migrate()
        id = pending(library, proposed_record)
        connection = library.db

        class FailedCommit:
            def __getattr__(self, name):
                return getattr(connection, name)

            def commit(self):
                raise OSError("Simulated disk-full commit")

        library.db = FailedCommit()
        with pytest.raises(OSError, match="disk-full"):
            library.approve(id, actor="trusted-reviewer")
        assert not connection.in_transaction
        assert status(library, id) == "pending"
        for table in ("wl_templates", "wl_versions", "wl_links", "wl_audit"):
            assert library.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0
        library.db = connection
        library.approve(id, actor="trusted-reviewer")
        assert library.get(proposed_record["id"]) == proposed_record
    finally:
        library.close()


def test_status_failure_rolls_back_template_revision_links_and_all_audit(
    proposals_db, proposed_record, monkeypatch
):
    library = proposals_db
    id = pending(library, proposed_record)
    original_execute = library.execute

    def fail_status(sql, params=()):
        if sql.startswith("UPDATE wl_proposals SET status='approved'"):
            raise RuntimeError("Simulated approval metadata failure")
        return original_execute(sql, params)

    monkeypatch.setattr(library, "execute", fail_status)
    with pytest.raises(RuntimeError, match="metadata failure"):
        library.approve(id, actor="trusted-reviewer")
    assert library.revision(proposed_record["id"]) == 0 and status(library, id) == "pending"
    for table in ("wl_templates", "wl_versions", "wl_links", "wl_audit"):
        assert library.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0


def test_approval_is_idempotent_and_cannot_reactivate_a_retired_template(
    proposals_db, proposed_record
):
    library = proposals_db
    id = pending(library, proposed_record)
    library.approve(id, actor="trusted-reviewer")
    assert (
        library.get(proposed_record["id"]) == proposed_record and status(library, id) == "approved"
    )
    audit = library.execute("SELECT * FROM wl_audit ORDER BY sequence").fetchall()
    library.approve(id, actor="trusted-reviewer")
    assert library.execute("SELECT * FROM wl_audit ORDER BY sequence").fetchall() == audit
    assert library.revision(proposed_record["id"]) == 1
    library.retire(proposed_record["id"], 1, actor="trusted-reviewer")
    library.approve(id, actor="trusted-reviewer")
    with pytest.raises(KeyError):
        library.get(proposed_record["id"])


def test_rejected_proposal_cannot_be_approved_or_change_a_world(proposals_db, proposed_record):
    library = proposals_db
    id = pending(library, proposed_record)
    library.reject(id, actor="trusted-reviewer")
    assert status(library, id) == "rejected" and not library.all()
    audit = library.execute("SELECT * FROM wl_audit ORDER BY sequence").fetchall()
    library.reject(id, actor="trusted-reviewer")
    assert library.execute("SELECT * FROM wl_audit ORDER BY sequence").fetchall() == audit
    with pytest.raises(ValueError, match="pending"):
        library.approve(id, actor="trusted-reviewer")
    assert (
        not library.all() and library.execute("SELECT COUNT(*) FROM wl_worlds").fetchone()[0] == 0
    )


def test_new_review_request_can_accept_previously_rejected_content(proposals_db, proposed_record):
    library = proposals_db
    rejected = library.propose(
        proposed_record, model="offline-test-model", prompt_version="v1", request_id="review-1"
    )
    library.reject(rejected, actor="trusted-reviewer")
    new = library.propose(
        proposed_record, model="offline-test-model", prompt_version="v1", request_id="review-2"
    )
    assert new != rejected and status(library, new) == "pending"
    library.approve(new, actor="trusted-reviewer")
    assert status(library, rejected) == "rejected"
    assert library.get(proposed_record["id"]) == proposed_record


def test_approval_rechecks_the_payload_digest_under_the_writer_lock(proposals_db, proposed_record):
    library = proposals_db
    id = pending(library, proposed_record)
    raw = library.execute("SELECT payload FROM wl_proposals WHERE id=?", (id,)).fetchone()[0]
    value = library._decode(raw)
    value["model"] = "tampered-model"
    with library.transaction():
        library.execute("UPDATE wl_proposals SET payload=? WHERE id=?", (dump(value), id))
    with pytest.raises(ValueError, match="digest"):
        library.approve(id, actor="trusted-reviewer")
    assert not library.all() and status(library, id) == "pending"


def test_a_proposal_cannot_overwrite_an_existing_template(proposals_db, proposed_record):
    library = proposals_db
    library.import_records([proposed_record])
    changed = deepcopy(proposed_record)
    changed["description"] += " Неподтверждённая подмена прежнего шаблона."
    id = pending(library, changed)
    with pytest.raises(ValueError, match="overwrite"):
        library.approve(id, actor="trusted-reviewer")
    assert library.get(proposed_record["id"]) == proposed_record
    assert library.revision(proposed_record["id"]) == 1 and status(library, id) == "pending"


def test_approval_never_silently_uses_a_new_component_revision(proposals_db, proposed_record):
    library = proposals_db
    material = deepcopy(proposed_record)
    material.update(id="wl_proposal_component", name="Материал основы")
    library.import_records([material])
    row = deepcopy(proposed_record)
    row["links"] = [
        {"relation": "component", "target": material["id"], "quantity": 1, "role": "основа"}
    ]
    original = pending(library, row)
    changed = deepcopy(material)
    changed["description"] += " Новая редакция после просмотра предложения."
    library.import_records([changed], expected={material["id"]: 1})
    with pytest.raises(ValueError, match="dependency"):
        library.approve(original, actor="trusted-reviewer")
    assert library.revision(row["id"]) == 0 and status(library, original) == "pending"
    reviewed = pending(library, row)
    assert reviewed != original
    library.approve(reviewed, actor="trusted-reviewer")
    assert (
        library.execute("SELECT target_revision FROM wl_links WHERE id=?", (row["id"],)).fetchone()[
            0
        ]
        == 2
    )


def test_legacy_unpinned_linked_proposal_requires_review_again(proposals_db, proposed_record):
    library = proposals_db
    material = deepcopy(proposed_record)
    material.update(id="wl_proposal_component", name="Материал основы")
    library.import_records([material])
    row = deepcopy(proposed_record)
    row["links"] = [
        {"relation": "component", "target": material["id"], "quantity": 1, "role": "основа"}
    ]
    payload = {
        "record": row,
        "model": "legacy-model",
        "prompt_version": "old-1",
        "engine_version": "world-library-1",
    }
    id = digest(payload)
    with library.transaction():
        library.execute("INSERT INTO wl_proposals VALUES(?,'pending',?)", (id, dump(payload)))
    with pytest.raises(ValueError, match="resubmission"):
        library.approve(id, actor="trusted-reviewer")
    assert library.revision(row["id"]) == 0 and status(library, id) == "pending"
