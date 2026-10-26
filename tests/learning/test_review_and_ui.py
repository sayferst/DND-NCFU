import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from rpg_vkr.application import Session
from rpg_vkr.learning import library
from rpg_vkr.learning.templates import apply_catalog, candidate, propose_catalog
from rpg_vkr.ui.learning_panel import LearningPanel


def test_review_revocation_rebuild_cancellation_and_query_time_rights(small_package, tmp_path):
    path, _ = small_package
    library.build(path, tmp_path / "lib")
    with library.Library(library.active_path(tmp_path / "lib"), writable=True) as db:
        id = next(r["id"] for r in db.candidates() if r["split"] == "train")
        db.review(id, "Особаявыдержка: наблюдай осторожно.", reviewer="owner", approved=True)
        assert db.search("особаявыдержка")
        before = db.stats()["indexed"]
        with pytest.raises(InterruptedError):
            db.rebuild_index(cancelled=lambda: True)
        assert db.stats()["indexed"] == before and db.search("особаявыдержка")
        db.rebuild_index()
        assert db.search("особаявыдержка")
        # Poisoning a cached transfer bit cannot bypass the authoritative source policy.
        with db.db:
            db.db.execute("UPDATE excerpts SET external=1 WHERE id=?", (id,))
        assert not db.search("особаявыдержка", remote=True)
        with db.db:
            db.db.execute("UPDATE reviews SET approved=0 WHERE id=?", (id,))
        assert not db.search("особаявыдержка")
        db.review(id, "Отзыв допуска.", reviewer="owner", approved=False)
        assert db.db.execute("SELECT count(*) FROM review_audit").fetchone()[0] == 2
        with pytest.raises(ValueError):
            db.review(id, "HP 500", reviewer="owner", approved=True)
        report = db.split_report()
        assert report["family_overlap"] == 0 and not report["raw_text_exported"]


def test_templates_require_review_flags_confirmation_and_persist_idempotently(
    small_package, learning_session, tmp_path, monkeypatch
):
    path, rows = small_package
    # Own fixture: an entity template rather than an invented live NPC.
    rows[0] = replace(rows[0], record_type="world_template")
    library.build(path, tmp_path / "lib")
    session = learning_session
    session._learning_flags = {"templates": True}
    with library.Library(library.active_path(tmp_path / "lib"), writable=True) as db:
        id = rows[0].record_id
        assert candidate(db, id)["status"] == "needs_review"
        with pytest.raises(ValueError):
            propose_catalog(db, session, id, request_id="meeting", name="Ливна", description="Плащ")
        db.review(id, "Собеседник занят своим делом.", reviewer="owner", approved=True)
        proposal = propose_catalog(
            db, session, id, request_id="meeting", name="Ливна", description="Ученик с сумкой писца"
        )
        before = session.to_dict(), session.dice.checkpoint()
        with pytest.raises(ValueError):
            apply_catalog(session, proposal)
        assert (session.to_dict(), session.dice.checkpoint()) == before
        assert not apply_catalog(session, proposal, confirmed=True)["already_applied"]
        restored = Session.from_dict(session.to_dict(), version=28)
        restored._learning_flags = {"templates": True}
        before = restored.to_dict(), restored.dice.checkpoint()
        assert apply_catalog(restored, proposal, confirmed=True)["already_applied"]
        assert (restored.to_dict(), restored.dice.checkpoint()) == before
        assert session.world.gold == before[0]["world"]["gold"]
        with pytest.raises(ValueError):
            apply_catalog(restored, replace(proposal, hero_id="different"), confirmed=True)


def test_admin_has_no_startup_work_auth_guard_and_discards_late_results(tmp_path):
    app = QApplication.instance() or QApplication([])
    console = SimpleNamespace(access=SimpleNamespace(authorized=False))
    panel = LearningPanel(console, directory=tmp_path / "library")
    assert not panel.busy and not panel.directory.exists()
    called = []
    assert not panel.start(lambda *args: called.append(True))
    console.access.authorized = True
    assert panel.start(lambda cancel, progress: ("result", {"ok": True}))
    panel.pool.waitForDone()
    app.processEvents()
    assert json.loads(panel.preview.toPlainText())["ok"]
    panel.finished(panel.serial - 1, ("result", {"stale": True}))
    assert "stale" not in panel.preview.toPlainText()
    console.access.authorized = False
    panel.finished(panel.serial, ("result", {"secret": True}))
    assert "secret" not in panel.preview.toPlainText()
    panel.shutdown()
    panel.finished(panel.serial, ("result", {"late": True}))
    assert "late" not in panel.preview.toPlainText()
    panel.close()
