"""Budget invariants across success, uncertainty, rejection and process restart."""

import json
from decimal import Decimal as D

import pytest

from rpg_vkr.learning.spend_journal import SpendJournal
from rpg_vkr.narrative.routerai import ModelQuote

QUOTE = ModelQuote("deepseek/deepseek-v4.1-flash", D(".001"), D(".002"), ())


def test_reservation_precedes_io_and_unknown_cost_cannot_be_reused(tmp_path):
    path = tmp_path / "spend.json"
    journal = SpendJournal(path, D(149), D(150))
    journal.reserve("first", D(".7"))
    assert D(json.loads(path.read_text())["accounted_total_rub"]) == D("149.7")
    journal.settle("first", None, QUOTE)
    with pytest.raises(ValueError, match="exhausted"):
        journal.reserve("second", D(".4"))
    with pytest.raises(FileExistsError):
        SpendJournal(path, D(0), D(150))


def test_only_verified_token_usage_releases_unused_reservation(tmp_path):
    journal = SpendJournal(tmp_path / "spend.json", D(149), D(150))
    journal.reserve("one", D(".7"))
    journal.settle("one", {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.15}, QUOTE)
    assert journal.accounted == D("149.2")
    journal.reserve("two", D(".8"))
    assert journal.accounted == D(150)
    with pytest.raises(ValueError):
        journal.reserve("one", D(".01"))
    with pytest.raises(ValueError):
        journal.settle("one", {}, QUOTE)


@pytest.mark.parametrize(
    "usage", [{}, {"cost": 0}, {"prompt_tokens": True, "completion_tokens": 0}]
)
def test_missing_or_untrusted_usage_retains_full_amount(tmp_path, usage):
    journal = SpendJournal(tmp_path / "spend.json", D(0), D(150))
    journal.reserve("one", D(1))
    journal.settle("one", usage, QUOTE)
    assert journal.accounted == 1


def test_quote_overrun_is_recorded_and_stops(tmp_path):
    journal = SpendJournal(tmp_path / "spend.json", D(0), D(150))
    journal.reserve("one", D(".1"))
    with pytest.raises(ValueError, match="exceeded"):
        journal.settle("one", {"prompt_tokens": 200, "completion_tokens": 0, "cost": 0.2}, QUOTE)
    assert journal.accounted == D(".2")


def test_provider_charge_above_the_token_quote_is_not_discarded(tmp_path):
    journal = SpendJournal(tmp_path / "spend.json", D(149), D(150))
    journal.reserve("one", D(".8"))
    journal.settle("one", {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.6}, QUOTE)
    assert journal.accounted == D("149.6")
    with pytest.raises(ValueError, match="exhausted"):
        journal.reserve("two", D(".5"))


@pytest.mark.parametrize("cost", [None, True, -1, "NaN", "Infinity", "bad"])
def test_token_counts_without_valid_reported_cost_cannot_release_reserve(tmp_path, cost):
    journal = SpendJournal(tmp_path / "spend.json", D(0), D(150))
    journal.reserve("one", D(1))
    journal.settle("one", {"prompt_tokens": 100, "completion_tokens": 50, "cost": cost}, QUOTE)
    assert journal.accounted == 1 and not journal.rows[0]["settled"]
