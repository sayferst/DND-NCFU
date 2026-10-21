"""Independent regressions from the owner's Images guide; no paid service calls."""

import base64
import json
from dataclasses import replace

import pytest
from test_images_client import PNG
from test_visual_controller import finish
from test_visual_controller import visual as visual_fixture
from test_visual_policy import catalog

from rpg_vkr.ui.knowledge import knowledge_entries
from rpg_vkr.visuals.client import ImagesTransport
from rpg_vkr.visuals.context import entity_target
from rpg_vkr.visuals.policy import FLUX, RECRAFT, payload, quote_model

visual = visual_fixture


def test_fixed_image_price_allows_documented_minimal_request():
    data = catalog(RECRAFT, "0.75", supported_parameters=[], per_request_limits={})
    quote = quote_model(data, RECRAFT, "1K")
    assert payload(quote, "pixel art") == {
        "model": RECRAFT,
        "prompt": "pixel art",
        "n": 1,
        "aspect_ratio": "1:1",
    }
    assert quote.total == 750000


def test_resolution_parameter_does_not_require_size_or_invented_limits():
    data = catalog(supported_parameters=["resolution"], per_request_limits={})
    quote = quote_model(data, FLUX, "2K")
    body = payload(quote, "pixel art")
    assert body["resolution"] == "2K" and "size" not in body


def test_reference_uses_documented_image_url_object():
    quote = quote_model(catalog(), FLUX, "1K", 1)
    data_url = "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert payload(quote, "pixel art", [data_url])["input_references"] == [
        {"type": "image_url", "image_url": {"url": data_url}}
    ]


def test_documented_usage_cost_is_rubles(qt_app, monkeypatch):
    transport = ImagesTransport()
    monkeypatch.setattr(
        transport,
        "read",
        lambda *a, **kw: json.dumps(
            {"data": [{"b64_json": base64.b64encode(PNG).decode()}], "usage": {"cost": 0.97}}
        ).encode(),
    )
    png, actual, receipt = transport.generate({"n": 1}, "fake-key")
    assert png.startswith(b"\x89PNG") and actual == 970000
    assert json.loads(receipt)["billing"]["currency"] == "RUB"


def test_individual_ordinary_item_stays_economy_model(visual):
    window, controller, fake = visual
    entry = next(e for e in knowledge_entries(window._session) if e.category == "items")
    target = entity_target(window._session, entry, shared=False)
    assert target.subject.startswith("entity:") and not target.common
    controller.request(target)
    finish(controller)
    assert len(fake.posts) == 1 and fake.posts[0]["model"] == RECRAFT


@pytest.mark.parametrize(
    "parameters, field, expected",
    [
        (["size"], "size", "1024x1024"),
        (["resolution"], "resolution", "1K"),
        (["size", "resolution"], "resolution", "1K"),
    ],
)
def test_documented_size_alternatives(parameters, field, expected):
    quote = quote_model(catalog(supported_parameters=parameters, per_request_limits={}), FLUX, "1K")
    body = payload(quote, "pixel art")
    assert body[field] == expected
    assert not {"size", "resolution"} <= body.keys()


def test_missing_reference_upper_limit_uses_one_advertised_reference():
    quote = quote_model(catalog(per_request_limits={}), FLUX, "1K", 1)
    assert quote.supports_references and quote.reference_limit == 1
    with pytest.raises(ValueError, match="input_references"):
        quote_model(catalog(per_request_limits={}), FLUX, "1K", 2)


@pytest.mark.parametrize(
    "patch, size",
    [
        (
            {
                "supported_parameters": [],
                "image_pricing": [{"unit": "image", "variant": "2K", "price": "0.97"}],
            },
            "1K",
        ),
        ({"supported_parameters": []}, "2K"),
        ({"per_request_limits": {"supported_resolutions": ["768"]}}, "1K"),
        ({"pricing_units": {"image_output": "megapixel"}}, "1K"),
        ({"pricing": {"image_output": "0.97", "reference_input": "0.1"}}, "1K"),
    ],
)
def test_no_unknown_resolution_or_unaccounted_cost_fallback(patch, size):
    with pytest.raises(ValueError):
        quote_model(catalog(**patch), FLUX, size)


@pytest.mark.parametrize("currency, expected", [(None, 970000), ("RUB", 970000), ("USD", None)])
def test_real_loopback_documented_request_and_billing(qt_app, currency, expected):
    from test_images_client import images_server

    usage = {"cost": 0.97}
    if currency:
        usage["currency"] = currency
    with images_server(usage=usage) as (url, records):
        quote = quote_model(
            catalog(supported_parameters=["resolution", "input_references"], per_request_limits={}),
            FLUX,
            "1K",
            1,
        )
        data_url = "data:image/png;base64," + base64.b64encode(PNG).decode()
        body = payload(quote, "pixel art", [data_url])
        png, actual, _ = ImagesTransport(test_base=url).generate(body, "fake-key")
        assert png.startswith(b"\x89PNG") and actual == expected
        assert len(records) == 1 and records[0][1] == "/images"
        assert records[0][3] == {
            "model": FLUX,
            "prompt": "pixel art",
            "n": 1,
            "resolution": "1K",
            "input_references": [{"type": "image_url", "image_url": {"url": data_url}}],
        }


def test_item_regeneration_switches_to_flux_with_same_saved_identity(visual):
    window, controller, fake = visual
    assert window.developer_console.access.login("995539")  # Technical routing diagnostics.
    entry = next(e for e in knowledge_entries(window._session) if e.category == "items")
    target = entity_target(window._session, entry, shared=False)
    before = window._session.to_dict(), window._session.dice.checkpoint()
    controller.request(target)
    finish(controller)
    first = controller.registry.latest_for(target.campaign, target.entity)
    controller.request(target, regenerate=True)
    finish(controller)
    assert [p["model"] for p in fake.posts] == [RECRAFT, FLUX]
    refs = fake.posts[-1]["input_references"]
    assert len(refs) == 1 and refs[0]["type"] == "image_url"
    decoded = base64.b64decode(refs[0]["image_url"]["url"].split(",", 1)[1], validate=True)
    assert decoded == controller.registry.asset_path(first).read_bytes()
    second = controller.registry.latest_for(target.campaign, target.entity)
    assert first["id"] in second["refs"] and second["subject"] == first["subject"]
    assert before == (window._session.to_dict(), window._session.dice.checkpoint())
    assert "FLUX" in controller.last_route and FLUX in controller.notice


@pytest.mark.parametrize(
    "category, eligible, expected",
    [
        ("items", True, RECRAFT),
        ("items", False, FLUX),
        ("people", False, FLUX),
        ("creatures", True, FLUX),
        ("places", False, FLUX),
        ("events", False, FLUX),
    ],
)
def test_pipeline_routes_by_object_class_not_model_inspector(visual, category, eligible, expected):
    window, controller, fake = visual
    entry = next(e for e in knowledge_entries(window._session) if e.category == "items")
    target = replace(
        entity_target(window._session, entry), category=category, economy_eligible=eligible
    )
    # Inspector selection describes a model; it is not a manual routing override.
    inspector = window.artist_panel.model_choice
    inspector.setCurrentIndex(inspector.findData(FLUX if expected == RECRAFT else RECRAFT))
    controller.request(target)
    finish(controller)
    assert len(fake.posts) == 1 and fake.posts[0]["model"] == expected


def test_preflight_error_explains_automatically_selected_model(visual, monkeypatch):
    from decimal import Decimal
    from types import SimpleNamespace

    window, controller, fake = visual
    assert window.developer_console.access.login("995539")  # Technical routing diagnostics.
    monkeypatch.setattr(
        fake, "metadata", lambda _: (SimpleNamespace(remaining=Decimal(100)), catalog(FLUX, "5.01"))
    )
    controller.request_scene()
    finish(controller)
    assert not fake.posts and not controller.registry.ledger()
    assert FLUX in controller.notice and "порога" in controller.notice


@pytest.mark.parametrize(
    "variant, field, value", [("2K", "resolution", "2K"), ("2048x2048", "size", "2048x2048")]
)
def test_priced_resolution_variant_is_an_alternative_to_parameter_list(variant, field, value):
    data = catalog(
        supported_parameters=[],
        per_request_limits={},
        image_pricing=[{"unit": "image", "variant": variant, "price": "1.51"}],
    )
    quote = quote_model(data, FLUX, "2K")
    assert payload(quote, "pixel art")[field] == value and quote.total == 1510000


@pytest.mark.parametrize(
    "variants",
    [
        [{"unit": "image", "variant": "1K", "price": "0.97"}],
        [
            {"unit": "image", "variant": "2K", "price": "1.51"},
            {"unit": "image", "variant": "2K", "price": "3.0"},
        ],
        [{"unit": "megapixel", "variant": "2K", "price": "0.97"}],
    ],
)
def test_specific_tariff_never_falls_back_to_another_resolution_price(variants):
    with pytest.raises(ValueError, match="цен"):
        quote_model(catalog(image_pricing=variants), FLUX, "2K")


def test_null_optional_catalog_metadata_allows_fixed_price_minimal_request():
    data = catalog(
        RECRAFT, "0.75", supported_parameters=None, per_request_limits=None, image_pricing=None
    )
    quote = quote_model(data, RECRAFT, "1K")
    assert "size" not in payload(quote, "pixel art") and "по умолчанию" in quote.size_description


@pytest.mark.parametrize("change", ["unique", "quest", "rare", "appearance"])
@pytest.mark.parametrize("shared", [True, False])
def test_unique_and_individualized_items_do_not_gain_economy_eligibility(
    visual, monkeypatch, change, shared
):
    from rpg_vkr.visuals import context

    window, controller, fake = visual
    entry = next(e for e in knowledge_entries(window._session) if e.category == "items")
    types, entities = context.live_records(window._session)
    entity = entities[entry.key]
    definition = types[entity["definition_id"]]
    if change == "unique":
        definition["properties"]["unique"] = True
    elif change == "quest":
        definition["categories"] = ["quest"]
    elif change == "rare":
        definition["rarity"] = "rare"
    else:
        entity.setdefault("state", {})["public_appearance"] = "Серебряная гравировка"
    monkeypatch.setattr(context, "live_records", lambda _: (types, entities))
    target = entity_target(window._session, entry, shared=shared)
    assert not target.common and not target.economy_eligible
    controller.request(target)
    finish(controller)
    assert len(fake.posts) == 1 and fake.posts[0]["model"] == FLUX


def test_flux_model_page_confirms_reference_support_even_with_incomplete_catalog():
    data = catalog(supported_parameters=[], per_request_limits={})
    quote = quote_model(data, FLUX, "1K", 1)
    data_url = "data:image/png;base64," + base64.b64encode(PNG).decode()
    body = payload(quote, "pixel art", [data_url])
    assert quote.reference_limit == 1 and quote.total == 970000
    assert body == {
        "model": FLUX,
        "prompt": "pixel art",
        "n": 1,
        "input_references": [{"type": "image_url", "image_url": {"url": data_url}}],
    }


def test_recraft_model_page_request_over_loopback(qt_app):
    from test_images_client import images_server

    data = catalog(RECRAFT, "0.75", supported_parameters=[], per_request_limits={})
    quote = quote_model(data, RECRAFT, "1K")
    with images_server(usage={"cost": 0.75}) as (url, records):
        png, actual, _ = ImagesTransport(test_base=url).generate(
            payload(quote, "pixel art"), "fake-key"
        )
        assert png.startswith(b"\x89PNG") and actual == 750000
        assert len(records) == 1 and records[0][3] == {
            "model": RECRAFT,
            "prompt": "pixel art",
            "n": 1,
            "aspect_ratio": "1:1",
        }
