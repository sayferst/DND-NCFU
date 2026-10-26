import pytest

from rpg_vkr.application import Session
from rpg_vkr.learning.evaluation import evaluate
from rpg_vkr.learning.library import build
from rpg_vkr.learning.scenarios import scenarios
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.story import story_context, story_proposal


@pytest.mark.parametrize(
    "query",
    [
        "Хочу решить, стоит ли соглашаться",
        "Я не согласен",
        "Согласиться пока не готов",
        "Можно согласиться?",
        "Хочу отказаться",
        "Взять с согласия владельца",
    ],
)
def test_consent_question_refusal_and_owner_permission_do_not_commit_hero(query):
    session = Session(seed=37)
    frame = build_frame(session)
    context = story_context(frame, "offline", query)
    before = session.to_dict(), session.dice.checkpoint()
    with pytest.raises(ValueError):
        story_proposal(
            {
                "message": {
                    "role": "assistant",
                    "content": "Вы решили согласиться на поручение и обещали вернуться к рассвету.",
                }
            },
            frame,
            query,
            context=context,
        )
    assert before == (session.to_dict(), session.dice.checkpoint())


def test_explicit_consent_and_promise_can_be_faithfully_restated():
    session = Session(seed=37)
    frame = build_frame(session)
    query = "Я соглашаюсь на поручение и обещаю вернуться к рассвету."
    assert story_proposal(
        {
            "message": {
                "role": "assistant",
                "content": "Вы согласились на поручение и обещали вернуться к рассвету.",
            }
        },
        frame,
        query,
    )


def test_live_deepseek_reply_denying_a_promise_is_not_a_positive_commitment():
    session = Session(seed=37)
    query = "Мастер, я только спрашиваю об условиях поручения и ещё не согласился."
    content = (
        "Пока это только разговор об условиях: вы ничего не обещали, не получили и "
        "ничем не связаны — никакого поручения ещё не принято."
    )
    assert story_proposal(
        {"message": {"role": "assistant", "content": content}}, build_frame(session), query
    )


def test_offline_comparison_uses_real_payload_and_validator_without_network(
    small_package, tmp_path, monkeypatch
):
    import socket

    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("network forbidden"))
    source, _ = small_package
    build(source, tmp_path / "lib")
    report = evaluate(tmp_path / "lib")
    assert report["scenarios"] == len(scenarios()) == 100 and len(report["rows"]) == 400
    assert report["canonical_state_and_rng_unchanged"]
    assert not report["paid_calls"] and not report["model_calls"]
    assert report["quality_gain"] == "NOT_MEASURED_MOCK_RESPONSES"
    assert all(not v["validator_mismatches"] for v in report["summary"].values())
    assert report["summary"]["B3"]["expected_method_hits_proxy"] > 0
    assert report["summary"]["B3"]["memory_available"] > 0
    assert report["summary"]["B3"]["max_extra_bytes"] <= 1800
