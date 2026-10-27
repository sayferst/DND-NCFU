from test_catalog_campaign import act, started

from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.records import Narration
from training.capture_session import candidates
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
