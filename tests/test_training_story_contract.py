"""Package regressions run against the real narrator boundary without model calls."""

from copy import deepcopy

import pytest
from test_team_encounters import hero, perform

from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.failures import NarrativeConflict
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.story import validate_story_text
from rpg_vkr.narrative.story_quality import check_story_quality


@pytest.mark.parametrize(
    "text",
    [
        "Вы получили ответ. Над пристанью повисла мёртвая тишина.",
        "С рассвета ломит спину. У пристани пахнет мокрым деревом.",
    ],
)
def test_metaphors_and_received_answer_do_not_create_rewards_or_death(text):
    session = hero()
    before, rng = deepcopy(session.to_dict()), session.dice.checkpoint()
    validate_story_text(text)
    check_story_quality(
        text, build_frame(session), "осматриваюсь", campaign=campaign_context(session)
    )
    assert session.to_dict() == before and session.dice.checkpoint() == rng


def test_unconfirmed_numeric_reward_remains_rejected():
    with pytest.raises(NarrativeConflict):
        validate_story_text("Вы получили 100 золотых монет и 100 очков опыта.")


def test_group_receipt_reaches_writer_and_cannot_end_an_active_encounter():
    session = hero()
    perform(session, "encounter", enemies=["first", "second"], allies=["friend"])
    perform(session, "attack", target="first", lethal=0)
    context = campaign_context(session)
    assert context["team_combat"]["active"]
    assert context["resolution"] and context["resolution"][-1]["rolled"]
    assert {a["id"] for a in context["team_combat"]["actors"]} == {"first", "second", "friend"}
    assert "seller" not in {a["id"] for a in context["team_combat"]["actors"]}
    with pytest.raises(NarrativeConflict):
        check_story_quality(
            "Схватка завершена. На пристани стало тихо.",
            build_frame(session),
            "атакую",
            campaign=context,
        )
