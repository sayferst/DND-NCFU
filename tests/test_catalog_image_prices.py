"""Replay price fields supplied by the owner; no real provider/image calls."""

import copy
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_visual_controller import finish
from test_visual_controller import visual as visual_fixture

from rpg_vkr.ui.knowledge import knowledge_entries
from rpg_vkr.visuals.context import entity_target
from rpg_vkr.visuals.policy import FLUX, RECRAFT, payload, quote_model

visual = visual_fixture
SOURCE = (
    Path(__file__).resolve().parents[1]
    / "docs/validation/image-quote-2026-10-20/owner-image-models.json"
)


def owner_catalog():
    return json.loads(SOURCE.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "size,total",
    [("768", 861645), ("1K", 969350), ("1.5K", 1184761), ("2K", 1507878), ("4K", 3877399)],
)
def test_owner_catalog_matches_selected_resolution_without_base_price_fallback(size, total):
    quote = quote_model(owner_catalog(), FLUX, size, 1)
    assert quote.total == total
    assert payload(quote, "pixel art", ["data:image/png;base64,fixture"])["resolution"] == size


def test_owner_top_level_reference_limit_is_used():
    quote = quote_model(owner_catalog(), FLUX, "768", 10)
    assert quote.reference_limit == 10 and quote.supports_references


def test_owner_recraft_stays_fixed_price_and_text_only():
    quote = quote_model(owner_catalog(), RECRAFT, "1K")
    assert quote.total == 753939 and not quote.supports_references
    assert payload(quote, "pixel art") == {
        "model": RECRAFT,
        "prompt": "pixel art",
        "n": 1,
        "aspect_ratio": "1:1",
    }


@pytest.mark.parametrize(
    "patch",
    [
        {"supported_image_sizes": ["768"]},
        {"supported_image_references": False},
        {"max_image_references": 0},
        {"max_image_references": True},
        {"max_image_count": 0},
    ],
)
def test_explicit_current_capability_restrictions_are_respected(patch):
    data = owner_catalog()
    data["data"][0].update(patch)
    with pytest.raises(ValueError):
        quote_model(data, FLUX, "1K", 1)


def test_conflicting_case_alias_prices_cannot_be_undercounted():
    data = owner_catalog()
    data["data"][0]["image_pricing"].append({"unit": "image", "variant": "1K", "price": 3.0})
    with pytest.raises(ValueError, match="цен"):
        quote_model(data, FLUX, "1K", 1)


def test_two_capability_locations_use_the_stricter_limit():
    data = owner_catalog()
    data["data"][0]["per_request_limits"] = {"max_input_references": 2}
    quote = quote_model(data, FLUX, "1K", 2)
    assert quote.reference_limit == 2
    with pytest.raises(ValueError):
        quote_model(data, FLUX, "1K", 3)


@pytest.mark.parametrize("category", ["items", "people"])
def test_regenerate_with_owner_prices_keeps_old_image_as_reference_and_posts_once(
    visual, monkeypatch, category
):
    window, controller, fake = visual
    data = owner_catalog()
    monkeypatch.setattr(
        fake, "metadata", lambda key: (SimpleNamespace(remaining=Decimal(100)), copy.deepcopy(data))
    )
    entry = next(e for e in knowledge_entries(window._session) if e.category == category)
    target = entity_target(window._session, entry, shared=False)
    original = window._session.to_dict(), window._session.dice.checkpoint()
    controller.request(target)
    finish(controller)
    first = controller.registry.latest_for(target.campaign, target.entity)
    assert first is not None
    fake.posts.clear()
    controller.request(target, regenerate=True)
    controller.request(target, regenerate=True)
    finish(controller)
    assert len(fake.posts) == 1
    assert fake.posts[0]["model"] == FLUX and fake.posts[0]["resolution"] == "1K"
    assert len(fake.posts[0]["input_references"]) == 1
    versions = controller.registry.versions(target.campaign, target.subject)
    assert len(versions) == 2 and first["id"] in versions[0]["refs"]
    assert controller.registry.ledger()[0]["expected_micros"] == 969350
    assert original == (window._session.to_dict(), window._session.dice.checkpoint())


def test_both_price_caps_can_be_saved_at_five_rubles(visual):
    from rpg_vkr.visuals.policy import VisualSettings

    window, controller, fake = visual
    controller.monthly.setValue(10)
    controller.economy.setValue(5)
    controller.quality.setValue(5)
    controller.save_settings()
    loaded = VisualSettings.load(controller.settings_path)
    assert loaded.economy_cap == loaded.quality_cap == 5_000_000
    assert not fake.posts and fake.gets == 0
    assert VisualSettings().economy_cap == 850000
    with pytest.raises(ValueError):
        VisualSettings(economy_cap=5_000_001)


@pytest.mark.parametrize("price,allowed", [("4.8", True), ("5.01", False)])
def test_recraft_uses_configured_cap_up_to_five_but_cannot_exceed_absolute_limit(
    visual, monkeypatch, price, allowed
):
    from dataclasses import replace

    window, controller, fake = visual
    data = owner_catalog()
    row = data["data"][1]
    row["pricing"]["image_output"] = price
    row["image_pricing"][0]["price"] = price
    monkeypatch.setattr(fake, "metadata", lambda _: (SimpleNamespace(remaining=Decimal(100)), data))
    controller.settings = replace(controller.settings, economy_cap=5_000_000)
    entry = next(e for e in knowledge_entries(window._session) if e.category == "items")
    controller.request(entity_target(window._session, entry))
    finish(controller)
    assert len(fake.posts) == int(allowed)
    assert len(controller.registry.ledger()) == int(allowed)


def test_scene_uses_several_saved_references_with_current_catalog_limit(visual, monkeypatch):
    window, controller, fake = visual
    monkeypatch.setattr(
        fake, "metadata", lambda _: (SimpleNamespace(remaining=Decimal(100)), owner_catalog())
    )
    for category in ("people", "items"):
        entry = next(e for e in knowledge_entries(window._session) if e.category == category)
        controller.request(entity_target(window._session, entry, shared=False))
        finish(controller)
    controller.request_scene()
    finish(controller)
    assert len(fake.posts) == 3 and fake.posts[-1]["model"] == FLUX
    assert len(fake.posts[-1]["input_references"]) == 2


def test_flux_cap_can_be_saved_at_ten_without_raising_recraft_or_default_budget(visual):
    from rpg_vkr.visuals.policy import VisualSettings

    window, controller, fake = visual
    controller.monthly.setValue(20)
    controller.economy.setValue(5)
    controller.quality.setValue(10)
    controller.save_settings()
    loaded = VisualSettings.load(controller.settings_path)
    assert loaded.economy_cap == 5_000_000 and loaded.quality_cap == 10_000_000
    assert controller.economy.maximum() == 5 and controller.quality.maximum() == 10
    assert not fake.posts and fake.gets == 0
    assert VisualSettings().quality_cap == 5_000_000
    assert VisualSettings().monthly_micros == 0
    with pytest.raises(ValueError):
        VisualSettings(quality_cap=10_000_001)


@pytest.mark.parametrize("price,allowed", [("9.8", True), ("10.01", False)])
def test_flux_respects_configured_ten_ruble_limit(visual, monkeypatch, price, allowed):
    from dataclasses import replace

    window, controller, fake = visual
    data = owner_catalog()
    data["data"][0]["image_pricing"][1]["price"] = price
    monkeypatch.setattr(fake, "metadata", lambda _: (SimpleNamespace(remaining=Decimal(100)), data))
    controller.settings = replace(
        controller.settings, quality_cap=10_000_000, monthly_micros=20_000_000
    )
    controller.request_scene()
    finish(controller)
    assert len(fake.posts) == int(allowed)
    assert len(controller.registry.ledger()) == int(allowed)
