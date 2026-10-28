"""Real funded work, escrow, physical delivery, replay and narration constraints."""

import json

import pytest
from test_catalog_campaign import act
from test_catalog_invariants import coins
from test_society_campaign import started

from rpg_vkr.application import Session
from rpg_vkr.domain.contracts import offers
from rpg_vkr.narrative.payment_guard import validate


def total(s):
    return coins(s) + sum(q.get("escrow_cp", 0) for q in s.gameplay["contracts"].values())


def test_accepted_work_requires_actual_gather_and_pays_only_once():
    s = started("mage")
    q = offers(s)[0]
    before = total(s)
    cash = s.gameplay["copper"]
    act(s, "contract", operation="accept", offer=q["id"])
    assert total(s) == before and s.gameplay["contracts"][q["id"]]["escrow_cp"] == q["reward_cp"]
    snapshot = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError, match="добыть"):
        act(s, "contract", operation="complete", offer=q["id"])
    assert (s.to_dict(), s.dice.checkpoint()) == snapshot
    for _ in range(12):
        act(s, "gather", material=q["resource"], quantity=2)
        if s.gameplay["activity"]["gathered"].get(q["resource"], 0) >= 2:
            break
    act(s, "contract", operation="complete", offer=q["id"])
    assert s.gameplay["copper"] == cash + q["reward_cp"] and s.gameplay["xp"] == 30
    assert total(s) == before and s.gameplay["contracts"][q["id"]]["status"] == "completed"
    snapshot = s.to_dict(), s.dice.checkpoint()
    with pytest.raises(ValueError):
        act(s, "contract", operation="complete", offer=q["id"])
    assert (s.to_dict(), s.dice.checkpoint()) == snapshot
    r = Session.from_dict(json.loads(json.dumps(s.to_dict())), version=31)
    assert r.to_dict() == s.to_dict() and r.dice.checkpoint() == s.dice.checkpoint()


def test_buying_from_requester_does_not_fulfil_gather_work():
    s = started("mage")
    q = offers(s)[0]
    act(s, "contract", operation="accept", offer=q["id"])
    for _ in range(2):
        item = next(
            i
            for i in s.gameplay["items"]
            if i["owner"] == "seller" and i.get("template") == q["resource"]
        )
        act(s, "buy", merchant="seller", item=item["id"])
    with pytest.raises(ValueError, match="добыть"):
        act(s, "contract", operation="complete", offer=q["id"])
    assert s.gameplay["xp"] == 0


@pytest.mark.parametrize("operation", ["cancel", "expire"])
def test_cancel_or_expiry_refunds_exact_escrow(operation):
    s = started("mage")
    q = offers(s)[0]
    before = total(s)
    act(s, "contract", operation="accept", offer=q["id"])
    if operation == "cancel":
        act(s, "contract", operation="cancel", offer=q["id"])
    else:
        for _ in range(15):
            act(s, "wait", minutes=1440)
    assert s.gameplay["contracts"][q["id"]]["status"] in ("cancelled", "expired")
    assert s.gameplay["contracts"][q["id"]]["escrow_cp"] == 0 and total(s) == before


@pytest.mark.parametrize(
    "text",
    [
        "Плата — четыре серебряных.",
        "Я заплачу 1,5 золотых.",
        "Награда: сто двадцать пять медных.",
        "Третья часть ваша.",
        "За работу заплачу 500 медных.",
    ],
)
def test_narrator_cannot_invent_payment(text):
    with pytest.raises(ValueError):
        validate(text, {"mechanics_revision": 3, "contracts": []})


@pytest.mark.parametrize(
    "text",
    [
        "Плата — двадцать четыре медных.",
        "Награда: 24 медных.",
        "Я не обещаю четыре серебряных.",
        "Это описание комнаты без цены.",
    ],
)
def test_registered_payment_and_direct_negation_are_allowed(text):
    validate(text, {"mechanics_revision": 3, "contracts": [{"reward_cp": 24}]})


def test_actual_receipt_price_allows_decimal_silver_and_long_number():
    validate("Цена: 1,5 серебряных.", {"mechanics_revision": 3, "receipt": {"price_cp": 15}})
    validate(
        "Цена: сто двадцать пять медных.", {"mechanics_revision": 3, "receipt": {"price_cp": 125}}
    )


def test_quests_are_reachable_through_real_widgets(window):
    from rpg_vkr.ui import unified_panel

    window._session = s = started("mage")
    unified_panel.refresh(window)
    assert window.quest_choice.count() > 0
    q = window.quest_choice.currentData()
    window.quest_buttons["accept"].click()
    assert s.gameplay["contracts"][q["id"]]["status"] == "accepted"
    for _ in range(12):
        act(s, "gather", material=q["resource"], quantity=2)
        if s.gameplay["activity"]["gathered"].get(q["resource"], 0) >= 2:
            break
    unified_panel.refresh(window)
    window.quest_buttons["complete"].click()
    assert s.gameplay["contracts"][q["id"]]["status"] == "completed" and s.gameplay["xp"] == 30
