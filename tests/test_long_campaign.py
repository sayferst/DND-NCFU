"""Exercise the actual long-run controller offline; a fake provider is explicitly labelled."""

from decimal import Decimal
from types import SimpleNamespace

from rpg_vkr.narrative.routerai import ModelQuote
from scripts.learning import long_campaign as runner


def test_three_actual_engine_turns_paired_requests_and_real_persistence(tmp_path, monkeypatch):
    quote = ModelQuote(runner.MODEL, Decimal(".000001"), Decimal(".000002"), ("max_tokens",))
    monkeypatch.setattr(runner, "parse_models", lambda _: [quote])
    monkeypatch.setattr(
        runner, "parse_allowance", lambda _: SimpleNamespace(remaining=Decimal(100))
    )

    def offline_request(url, **kwargs):
        if "payload" not in kwargs:
            return {}
        return {
            "model": runner.MODEL,
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Ветер колышет траву у дороги."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }

    monkeypatch.setattr(runner, "request", offline_request)
    result = runner.execute("test-not-a-key", tmp_path / "run", 3, 2, Decimal(0), Decimal(1))
    assert result["calls"] == 5 and result["completed_turns"] == 3
    assert result["paired_control_states"] == 2 and result["json_sqlite_replay_rng_equal"]
    assert Decimal(result["accounted_total_rub"]) == Decimal(".0007")
