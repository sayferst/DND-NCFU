"""Real disk round trips, isolation of slots and recoverable I/O failures."""

import json

import pytest

from rpg_vkr.application import Session
from rpg_vkr.storage.slots import MAX_SAVE_BYTES, SaveError, SaveSlots, default_save_directory


def test_three_slots_persist_independently_and_can_be_overwritten(tmp_path):
    store = SaveSlots(tmp_path / "сохранения")
    for slot in (1, 2, 3):
        assert not store.info(slot).occupied
        session = Session(seed=slot)
        session.submit("помочь")
        session.submit("бросить d20")
        store.save(slot, session)
    reopened = SaveSlots(store.directory)
    original = {slot: reopened.load(slot).to_dict() for slot in (1, 2, 3)}
    assert [original[slot]["seed"] for slot in (1, 2, 3)] == [1, 2, 3]
    assert "действий: 2" in reopened.info(1).description
    replacement = Session(seed=42)
    replacement.submit("бросить d20")
    reopened.save(2, replacement)
    assert reopened.load(2).to_dict() == replacement.to_dict()
    assert reopened.load(1).to_dict() == original[1]
    assert reopened.load(3).to_dict() == original[3]


def test_disk_reload_continues_the_random_sequence(tmp_path):
    store = SaveSlots(tmp_path)
    session = Session(seed=42)
    session.submit("бросить d20")
    store.save(1, session)
    restored = SaveSlots(tmp_path).load(1)
    assert restored.submit("бросить d20").roll.value == 1
    assert restored.to_dict() == Session.from_dict(restored.to_dict()).to_dict()


def test_delete_only_removes_selected_slot(tmp_path):
    store = SaveSlots(tmp_path)
    for slot in (1, 2, 3):
        store.save(slot, Session(seed=slot))
    store.delete(2)
    assert not store.info(2).occupied
    assert store.load(1).dice.seed == 1
    assert store.load(3).dice.seed == 3
    with pytest.raises(SaveError, match="пуста"):
        store.load(2)


@pytest.mark.parametrize("slot", [0, 4, -1, True, "../other"])
def test_invalid_slots_cannot_access_arbitrary_paths(tmp_path, slot):
    store = SaveSlots(tmp_path)
    for operation in [store.load, store.delete, store.info]:
        with pytest.raises(ValueError):
            operation(slot)
    with pytest.raises(ValueError):
        store.save(slot, Session(seed=42))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("content", [b"{broken", b"[]", b"{}", b"\xff"])
def test_corrupt_save_is_reported_and_not_modified(tmp_path, content):
    path = tmp_path / "slot-1.json"
    path.write_bytes(content)
    store = SaveSlots(tmp_path)
    with pytest.raises(SaveError, match="повреждено"):
        store.load(1)
    assert store.info(1).occupied
    assert path.read_bytes() == content


def test_unsupported_schema_is_rejected(tmp_path):
    store = SaveSlots(tmp_path)
    store.save(1, Session(seed=42))
    path = tmp_path / "slot-1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = 999
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SaveError, match="версию"):
        store.load(1)


@pytest.mark.parametrize("timestamp", [None, "not-a-date", "9999-12-31T23:59:59-23:59"])
def test_invalid_timestamp_does_not_crash_slot_listing(tmp_path, timestamp):
    store = SaveSlots(tmp_path)
    store.save(1, Session(seed=42))
    path = tmp_path / "slot-1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["saved_at"] = timestamp
    path.write_text(json.dumps(data), encoding="utf-8")
    assert store.info(1).description == "повреждено или недоступно"
    with pytest.raises(SaveError, match="повреждено"):
        store.load(1)


def test_failed_atomic_replace_preserves_previous_save(tmp_path, monkeypatch):
    store = SaveSlots(tmp_path)
    store.save(1, Session(seed=1))
    previous = (tmp_path / "slot-1.json").read_bytes()

    def fail_replace(*args):
        raise OSError("Simulated disk failure")

    monkeypatch.setattr("rpg_vkr.storage.slots.os.replace", fail_replace)
    with pytest.raises(SaveError, match="Не удалось сохранить"):
        store.save(1, Session(seed=2))
    assert (tmp_path / "slot-1.json").read_bytes() == previous
    assert list(tmp_path.glob("*.tmp")) == []


def test_unwritable_directory_has_clear_error(tmp_path):
    path = tmp_path / "not-a-directory"
    path.write_text("keep me", encoding="utf-8")
    with pytest.raises(SaveError, match="Не удалось сохранить"):
        SaveSlots(path).save(1, Session(seed=42))
    assert path.read_text(encoding="utf-8") == "keep me"


def test_oversized_file_is_rejected(tmp_path):
    (tmp_path / "slot-1.json").write_bytes(b" " * (MAX_SAVE_BYTES + 1))
    with pytest.raises(SaveError, match="повреждено"):
        SaveSlots(tmp_path).load(1)


def test_save_location_can_be_selected_without_changing_checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("RPG_VKR_DATA_DIR", str(tmp_path / "user-data"))
    assert default_save_directory() == tmp_path / "user-data" / "saves"
