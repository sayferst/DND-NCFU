"""Coverage is based on active evidence, not words in a character's repertoire."""

from training.gm_mechanics import fireball_evidence, hp_observation, prose_evidence


def test_inventory_mentions_do_not_become_executed_spell_or_repair():
    row = {
        "combat_state_before": [
            {
                "name": "A",
                "spells": "Fly, Mending, Cure Wounds",
                "description": "a merchant who repairs armor",
            }
        ]
    }
    assert fireball_evidence(row) == {}
    row["commands_norm"] = ['!cast "Violet Gate"']
    assert fireball_evidence(row) == {"spell_casting": "RECORDED_COMMAND_NOT_RULE_OR_SUCCESS_PROOF"}


def test_zero_hp_does_not_assert_death_and_unknown_hp_never_becomes_zero():
    assert hp_observation("<Healthy>") is None
    assert hp_observation(None) is None
    assert hp_observation("<-2/10 HP; Hurt>") is None
    tags = fireball_evidence(
        {
            "combat_state_before": [{"name": "A", "hp": "<4/10 HP; Hurt>"}],
            "combat_state_after": [{"name": "A", "hp": "<0/10 HP; Down>"}],
        }
    )
    assert tags["damage"] == "OBSERVED_NUMERIC_STATE_DELTA"
    assert tags["zero_hp"] == "OBSERVED_ZERO_HP_NOT_PROOF_OF_DEATH"
    assert "death_stabilization" not in tags


def test_ambiguous_names_or_unknown_effects_do_not_manufacture_deltas():
    row = {
        "combat_state_before": [{"name": "A"}, {"name": "A"}],
        "combat_state_after": [{"name": "A", "hp": "<0/10 HP; Down>"}],
    }
    assert fireball_evidence(row) == {}
    row["combat_state_before"] = [{"name": "A"}]
    row["combat_state_after"] = [{"name": "A", "effects": ""}]
    assert fireball_evidence(row) == {}


def test_new_homebrew_actions_remain_observed_without_invented_rule_semantics():
    row = {
        "commands_norm": ['!cast "Silver Orchard"'],
        "automation_results": ["B gained Violet Feather."],
        "after_utterances": ["The feathers drift around the doorway."],
    }
    tags = fireball_evidence(row)
    assert "spell_casting" in tags and "conditions_effects" in tags
    assert "physical_capability_limits" not in tags and "healing" not in tags
    assert (
        prose_evidence("I repair the armor.")["repair"] == "NARRATIVE_MENTION_NOT_VERIFIED_MECHANIC"
    )


def test_names_brands_and_the_rest_are_not_crafting_or_rest_mechanics():
    tags = prose_evidence(
        "Rylo Craft attacks. Bravo to Dwarven Forge. The rest of the group waits."
    )
    assert "crafting" not in tags and "rest_exhaustion" not in tags
    assert "trade_economy" not in prose_evidence("The blade fails to find purchase.")
    assert "crafting" in prose_evidence("I assemble the pieces into a crude tool.")
    assert "rest_exhaustion" in prose_evidence("We take a short rest in the cave.")
