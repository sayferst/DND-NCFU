import pytest
from test_catalog_campaign import act, started

from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.story import story_context, story_proposal


def test_writer_question_keeps_last_receipt_and_current_mp():
    s = started("mage")
    act(s, "cast", spell="light", target="hero")
    frame = build_frame(s)
    query = "Мастер, что уже произошло?"
    ctx = story_context(
        frame, "deepseek/deepseek-v4.1-flash", query, campaign=campaign_context(s, query=query)
    )
    assert ctx["receipt"] is None
    assert ctx["last_committed_receipt"]["committed"]
    assert ctx["current_resources"]["mp"] == s.gameplay["mp"]
    with pytest.raises(ValueError, match="Мана героя"):
        story_proposal(
            {
                "message": {
                    "role": "assistant",
                    "content": "Вы стоите у переправы; здоровье, силы и мана полны.",
                }
            },
            frame,
            query,
            context=ctx,
        )
    with pytest.raises(ValueError, match="другом языке"):
        story_proposal(
            {"message": {"role": "assistant", "content": "Вокруг струится cold-белое сияние."}},
            frame,
            query,
            context=ctx,
        )
