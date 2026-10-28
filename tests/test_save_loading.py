"""Slot listing avoids replay; actual loading validates on a worker with responsive Qt."""

import json
from threading import Event, get_ident

import pytest
from PySide6.QtCore import QTimer

from rpg_vkr.application import Session
from rpg_vkr.storage.slots import SaveError, SaveSlots
from rpg_vkr.ui.save_loading import read_with_progress


def test_listing_never_replays_but_load_still_validates(tmp_path, monkeypatch):
    store = SaveSlots(tmp_path)
    s = Session(seed=37)
    s.submit("бросить d20")
    store.save(1, s)

    def forbidden(*args, **kwargs):
        raise ValueError("Deliberate invalid replay")

    monkeypatch.setattr(Session, "from_dict", forbidden)
    assert "действий: 1" in store.info(1).description
    with pytest.raises(SaveError, match="повреждено"):
        store.load(1)
    data = json.loads((tmp_path / "slot-1.json").read_text(encoding="utf-8"))
    data["saved_at"] = None
    (tmp_path / "slot-1.json").write_text(json.dumps(data), encoding="utf-8")
    assert store.info(1).description == "повреждено или недоступно"


def test_gui_events_continue_while_save_reader_is_busy(qt_app):
    import time

    main_thread = get_ident()
    release = Event()
    session = Session(seed=37)
    ticks = []

    class SlowStore:
        def load(self, slot):
            assert slot == 1 and get_ident() != main_thread
            assert release.wait(timeout=5), "GUI timer never executed"
            time.sleep(0.02)
            return session

    QTimer.singleShot(20, lambda: (ticks.append(True), release.set()))
    assert read_with_progress(None, SlowStore(), 1) is session
    assert ticks


def test_worker_error_is_preserved_for_the_existing_error_dialog(qt_app):
    class BrokenStore:
        def load(self, slot):
            raise SaveError("Проверка намеренно отклонена")

    with pytest.raises(SaveError, match="отклонена"):
        read_with_progress(None, BrokenStore(), 1)
