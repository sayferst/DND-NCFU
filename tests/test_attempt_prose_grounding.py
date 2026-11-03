"""Real Faun failures and unseen item combinations use the same receipt guard."""

import pytest

from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.failures import NarrativeConflict
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.story_quality import check_story_quality
from rpg_vkr.narrative.strategic_critic import inspect
from training.game_benchmark import execute_case


@pytest.mark.parametrize(
    "case,text,code",
    [
        (
            "bow_damage",
            "Вы разобрали свой лук, используя метлу и древко. "
            "Удочка изготовлена из поврежденных материалов, состояние её плохое.",
            "UNCONFIRMED_CRAFT_INPUT",
        ),
        (
            "bow_partial",
            "Вы разобрали лук, заменив его древком на удочку. "
            "Удочка изготовлена из ясеневого древка, которое вы нашли. Она крепкая и прочная.",
            "UNCONFIRMED_FINISHED_PRODUCT",
        ),
    ],
)
def test_actual_faun_false_results_are_rejected(case, text, code):
    s, action = execute_case(case)
    context = campaign_context(s)
    with pytest.raises(NarrativeConflict) as error:
        check_story_quality(text, build_frame(s), action, campaign=context)
    assert code in str(error.value)


@pytest.mark.parametrize(
    "case,text",
    [
        ("bow_damage", "Материалы повреждены. Изготовить снасть не удалось."),
        ("bow_partial", "Получилась незавершённая заготовка. Рядом стоит метла."),
        (
            "bow_success",
            "Вы успешно соорудили удочку из обломков лука. "
            "Теперь у вас есть импровизированная удочка.",
        ),
    ],
)
def test_supported_outcomes_and_unused_scenery_are_not_rejected(case, text):
    s, action = execute_case(case)
    check_story_quality(text, build_frame(s), action, campaign=campaign_context(s))


def test_unseen_clay_work_cannot_silently_consume_an_unselected_copper_wire():
    proof = {
        "committed": True,
        "free_attempt": {
            "plan": {"operation": "transform", "items": ["clay"], "tool": "knife"},
            "item_changes": [{"after": {"kind": "salvage", "form": ""}}],
        },
    }
    objects = [{"id": "wire", "name": "Медная проволока"}, {"id": "knife", "name": "Нож"}]
    bad = inspect(proof, "Вы работаете с помощью проволоки.", objects=objects)
    assert any(f["code"] == "UNCONFIRMED_CRAFT_INPUT" for f in bad)
    assert not inspect(proof, "Получилась заготовка. Проволока лежит рядом.", objects=objects)
    proof["free_attempt"]["plan"]["items"].append("wire")
    assert not inspect(proof, "Вы работаете с помощью проволоки.", objects=objects)
