"""Queue integration on real Qt windows; fake transport, no external services."""

import time
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication
from response_cases import new_session
from test_images_client import PNG
from test_local_narrator import wait_for
from test_visual_policy import catalog

from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.knowledge import knowledge_entries
from rpg_vkr.ui.main_window import MainWindow
from rpg_vkr.visuals.client import ImageError
from rpg_vkr.visuals.context import entity_target, scene_target
from rpg_vkr.visuals.policy import FLUX, RECRAFT


class FakeTransport:
    def __init__(self):
        self.posts = []
        self.gets = 0
        self.delay = 0
        self.error = False

    def metadata(self, key):
        self.gets += 1
        time.sleep(self.delay)
        return SimpleNamespace(remaining=Decimal(100)), {
            "data": [*catalog(RECRAFT, "0.75")["data"], *catalog(FLUX, "0.97")["data"]]
        }

    def generate(self, body, key):
        self.posts.append(body)
        time.sleep(self.delay)
        if self.error:
            raise ImageError("network", "Проверочная ошибка сети")
        return PNG, 750000, "fake-receipt"


@pytest.fixture
def visual(qt_app, tmp_path, monkeypatch):
    window = MainWindow(session=new_session(), saves=SaveSlots(tmp_path / "saves"))
    window._confirm = lambda *_: True
    controller = window.visuals
    fake = FakeTransport()
    controller.worker.transport = fake
    controller.settings = replace(controller.settings, monthly_micros=10000000, consent=True)
    monkeypatch.setattr(controller, "key", lambda: "fake-key")
    monkeypatch.setattr(controller, "ask", lambda *_: True)
    monkeypatch.setattr(controller, "view", lambda *_: None)
    yield window, controller, fake
    wait_for(qt_app, lambda: not controller.worker.busy and not controller.active)
    window.close()


def finish(controller):
    wait_for(QApplication.instance(), lambda: not controller.active and not controller.worker.busy)


def test_create_cache_no_canon_change_and_no_second_charge(visual):
    window, controller, fake = visual
    entry = next(e for e in knowledge_entries(window._session) if e.category == "items")
    before = window._session.to_dict(), window._session.dice.checkpoint()
    target = entity_target(window._session, entry)
    controller.request(target)
    controller.request(target)
    finish(controller)
    assert len(fake.posts) == 1 and fake.posts[0]["model"] == RECRAFT
    assert controller.registry.latest_for(target.campaign, target.entity)
    controller.request(target)
    assert len(fake.posts) == 1 and fake.gets == 1
    assert before == (window._session.to_dict(), window._session.dice.checkpoint())


def test_npc_portrait_then_scene_passes_same_reference_bytes(visual):
    window, controller, fake = visual
    entry = next(e for e in knowledge_entries(window._session) if e.category == "people")
    controller.request(entity_target(window._session, entry))
    finish(controller)
    portrait = controller.registry.latest_for(scene_target(window._session).campaign, entry.key)
    controller.request_scene()
    finish(controller)
    body = fake.posts[-1]
    assert body["model"] == FLUX and body["input_references"][0]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    scene = scene_target(window._session)
    assert portrait["id"] in controller.registry.versions(scene.campaign, scene.subject)[0]["refs"]
    assert portrait["subject"] not in body["prompt"]


def test_failed_post_keeps_reserve_and_never_retries(visual):
    window, controller, fake = visual
    fake.error = True
    target = scene_target(window._session)
    controller.request(target)
    finish(controller)
    assert len(fake.posts) == 1
    row = controller.registry.ledger()[0]
    assert row["status"] == "uncertain" and row["actual_micros"] is None
    controller.request(target)
    finish(controller)
    assert len(fake.posts) == 1


def test_cancel_metadata_no_post_and_cancel_post_retains_result(visual):
    window, controller, fake = visual
    fake.delay = 0.05
    controller.request_scene()
    controller.cancel()
    finish(controller)
    assert not fake.posts
    controller.request_scene()
    wait_for(QApplication.instance(), lambda: controller.stage == "generate")
    controller.cancel()
    finish(controller)
    assert len(fake.posts) == 1 and controller.registry.ledger()[0]["status"] == "succeeded"


def test_zero_budget_or_revoked_consent_does_not_post(visual):
    window, controller, fake = visual
    controller.settings = replace(controller.settings, monthly_micros=0)
    controller.request_scene()
    assert fake.gets == 0 and not fake.posts
    controller.settings = replace(controller.settings, monthly_micros=10000000)
    controller.request_scene()
    controller.settings = replace(controller.settings, consent=False)
    finish(controller)
    assert not fake.posts


def test_declined_confirmation_and_world_change_cost_nothing(visual, monkeypatch):
    window, controller, fake = visual
    monkeypatch.setattr(controller, "ask", lambda *_: False)
    controller.request_scene()
    finish(controller)
    assert not fake.posts
    controller.request_scene()
    window._session = new_session()
    finish(controller)
    assert not fake.posts and not controller.registry.ledger()


def test_unknown_price_or_over_flux_cap_never_posts(visual, monkeypatch):
    window, controller, fake = visual
    for price in ["5.01", "NaN"]:
        monkeypatch.setattr(
            fake,
            "metadata",
            lambda key, p=price: (SimpleNamespace(remaining=Decimal(100)), catalog(FLUX, p)),
        )
        controller.request_scene()
        finish(controller)
    assert not fake.posts and not controller.registry.ledger()


def test_missing_reference_capability_never_silently_drops_identity(visual, monkeypatch):
    window, controller, fake = visual
    entry = next(e for e in knowledge_entries(window._session) if e.category == "people")
    controller.request(entity_target(window._session, entry))
    finish(controller)

    def metadata(key):
        data = catalog()
        data["data"][0]["per_request_limits"]["max_input_references"] = 0
        return SimpleNamespace(remaining=Decimal(100)), data

    monkeypatch.setattr(fake, "metadata", metadata)
    controller.request_scene()
    finish(controller)
    assert len(fake.posts) == 1


def test_missing_image_store_does_not_break_text_game(qt_app, tmp_path):
    import sqlite3

    root = tmp_path / "visuals"
    root.mkdir()
    with sqlite3.connect(root / "visuals.sqlite3") as db:
        db.execute("CREATE TABLE unrelated(x)")
    window = MainWindow(session=new_session(), saves=SaveSlots(tmp_path / "saves"))
    try:
        assert window._session.generated_world and not hasattr(window, "visuals")
    finally:
        window.close()
