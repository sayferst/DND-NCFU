from decimal import Decimal

import pytest

from rpg_vkr.learning import live_probe as pilot
from rpg_vkr.learning.library import build
from rpg_vkr.narrative.routerai import KeyAllowance, ModelQuote


def test_pilot_is_dry_by_default_and_never_opens_connection(monkeypatch, tmp_path):
    monkeypatch.setattr(pilot, "request", lambda *a, **k: pytest.fail("unexpected request"))
    report = pilot.live_probe("", tmp_path)
    assert report["status"] == "READY_NOT_RUN" and report["max_calls"] == 8
    assert report["model"] == "deepseek/deepseek-v4.1-flash"


@pytest.mark.parametrize("cap,expected_posts", [(Decimal("0.001"), 0), (Decimal("5"), 8)])
def test_pilot_reserves_budget_before_posts_uses_only_requested_model_and_never_applies_prose(
    small_package, tmp_path, monkeypatch, cap, expected_posts
):
    package, _ = small_package
    directory = tmp_path / "lib"
    build(package, directory)
    quote = ModelQuote(pilot.MODEL, Decimal("0.00001"), Decimal("0.00002"), ("max_tokens",))
    monkeypatch.setattr(pilot, "parse_models", lambda _: [quote])
    monkeypatch.setattr(pilot, "parse_allowance", lambda _: KeyAllowance(cap, Decimal(0), cap))
    posts = []

    def request(url, *, key="", payload=None):
        if payload is None:
            return {}
        assert key == "synthetic-test-key" and payload["model"] == pilot.MODEL
        assert payload["max_tokens"] == pilot.MAX_OUTPUT
        posts.append(payload)
        return {
            "model": pilot.MODEL,
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "У дороги тихо. Ветер качает ветви возле стены.",
                    },
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }

    monkeypatch.setattr(pilot, "request", request)
    report = pilot.live_probe("synthetic-test-key", directory, execute=True)
    assert len(posts) == expected_posts
    assert Decimal(report["reserved_upper_rub"]) <= cap
    assert report["canonical_state_and_rng_unchanged"]
    assert not report["raw_corpus_sent"] and not report["training_started"]
    assert "synthetic-test-key" not in str(report)


def test_pilot_forbids_cross_host_redirects_and_arbitrary_endpoints():
    with pytest.raises(ValueError, match="RouterAI"):
        pilot.request("https://example.org/steal", key="synthetic-key")
    with pytest.raises(ValueError, match="Перенаправление"):
        pilot.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.org/")
