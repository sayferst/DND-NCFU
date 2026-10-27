from test_adventure import world_value
from test_unified_rules import hero

from rpg_vkr.application import Session
from rpg_vkr.domain.adventure import build_world
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.story import story_context


def test_new_prologue_can_exceed_old_cap_without_changing_old_seed_writer():
    s = hero()
    value = world_value()
    value["opening"] = "Над мостом встаёт ясное утро. " * 170
    seed = build_world(value, s, "own-long-prologue")
    assert seed.version == 2 and len(seed.opening) > 3500
    s.start_world(seed)
    assert Session.from_dict(s.to_dict()).to_dict() == s.to_dict()
    frame = build_frame(s)
    short = story_context(frame, "deepseek/deepseek-v4.1-flash", "Сколько стоит?")
    long = story_context(frame, "deepseek/deepseek-v4.1-flash", "Вступление в начале кампании")
    assert long["writing_profile"]["num_predict"] > short["writing_profile"]["num_predict"]
    assert "1–3 предложения" in short["writing_profile"]["length"]
