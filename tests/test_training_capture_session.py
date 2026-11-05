from test_catalog_campaign import act, started

from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.records import Narration
from training.capture_session import candidates, episodes
from training.schema import validate


def test_capture_uses_real_replayed_receipt_without_inventing_review():
    s = started("mage")
    act(s, "cast", spell="light", target="hero")
    s.add_narration(
        Narration(
            len(s.turns),
            "deepseek/deepseek-v4.1-flash",
            "Ладонь освещает мягкий свет.",
            build_frame(s).fingerprint,
        )
    )
    rows = candidates({"schema_version": 31, "session": s.to_dict()})
    assert len(rows) == 1 and rows[0]["engine_receipt"]["committed"]
    assert rows[0]["review_status"] == "pending"
    assert validate(rows[0]) == (False, "rights_or_review")
    assert "private_plot" not in str(rows)
    assert "Код переправы" not in str(rows)


def test_collector_captures_context_before_actual_transaction_and_marks_fixture():
    s = started("mage")
    before_mp = s.gameplay["mp"]
    act(s, "cast", spell="light", target="hero")
    after_mp = s.gameplay["mp"]
    s.add_narration(
        Narration(
            len(s.turns), "fixture:test", "В ладони светится огонёк.", build_frame(s).fingerprint
        )
    )
    data = {"schema_version": 31, "session": s.to_dict()}
    row = episodes(data)[0]
    assert before_mp > after_mp
    assert row["transaction"]["before"]["hero_resources"]["mp"] == before_mp
    assert row["transaction"]["after"]["hero_resources"]["mp"] == after_mp
    assert row["synthetic"] is True and row["review"]["human_rating"] is None
    candidate = candidates(data)[0]
    candidate.update(review_status="approved", rights_status="permitted")
    assert validate(candidate) == (False, "fixture_not_training_data")
