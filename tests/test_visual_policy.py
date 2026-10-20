import pytest

from rpg_vkr.visuals.policy import FLUX, RECRAFT, VisualSettings, payload, quote_model, route


def catalog(model=FLUX, price="0.97", **patch):
    return {
        "data": [
            {
                "id": model,
                "pricing": {"image_output": price},
                "pricing_units": {"image_output": "image"},
                "supported_parameters": ["size", "input_references"],
                "per_request_limits": {
                    "supported_resolutions": ["768", "1K", "1.5K", "2K", "4K"],
                    "max_input_references": 3,
                },
                **patch,
            }
        ]
    }


def test_routing_prices_size_variants_and_text_only_recraft():
    assert route("items", True, False) == RECRAFT
    assert route("people", False, False) == FLUX
    assert route("items", True, True) == FLUX
    q = quote_model(
        catalog(image_pricing=[{"unit": "image", "variant": "768", "price": "0.86"}]), FLUX, "768"
    )
    assert q.total == 860000
    assert payload(q, "pixel art", ["data:image/png;base64,test"])["input_references"]
    q = quote_model(catalog(RECRAFT, "0.75"), RECRAFT, "1K")
    with pytest.raises(ValueError):
        payload(q, "test", ["x"])


@pytest.mark.parametrize(
    "patch",
    [
        {"pricing_units": {"image_output": "token"}},
        {"pricing": {"image_output": "0.75", "prompt": "0.01"}},
        {"pricing": {"image_output": "NaN"}},
        {"supported_parameters": []},
        {"per_request_limits": {}},
        {"per_request_limits": {"supported_resolutions": ["1K"], "max_input_references": "many"}},
    ],
)
def test_unknown_cost_or_capability_blocks_before_post(patch):
    with pytest.raises(ValueError):
        quote_model(catalog(**patch), FLUX, "1K", 1)


def test_zero_budget_defaults_and_nonsecret_settings(tmp_path):
    s = VisualSettings()
    assert (
        s.monthly_micros == 0 and s.confirm and s.economy_cap == 850000 and s.quality_cap == 5000000
    )
    s.save(tmp_path / "visual.json")
    assert VisualSettings.load(tmp_path / "visual.json") == s
    with pytest.raises(ValueError):
        VisualSettings(quality_cap=5000001)
    with pytest.raises(ValueError):
        VisualSettings(monthly_micros=-1)
