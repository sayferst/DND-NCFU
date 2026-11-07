"""Translation checks never masquerade as a meaning or human review."""

import pytest

from training.gm_translation import diagnostics, fragments, human_strings, run, safe_batch


def test_numeric_and_negation_changes_require_review():
    assert "NUMERIC_VALUES_DIFFER" in diagnostics(
        "It takes 6 damage.", "Он получает 9 урона.", "en-ru"
    )
    assert "NEGATION_REQUIRES_MEANING_REVIEW" in diagnostics(
        "You cannot fly.", "Ты можешь летать.", "en-ru"
    )
    assert not diagnostics("It takes 6 damage.", "Он получает 6 урона.", "en-ru")


def test_context_translation_preserves_machine_ids_and_typed_receipts():
    assert list(
        human_strings(
            {
                "name": "Old Oak",
                "id": "Old_Oak_01",
                "hp": 8,
                "commands_norm": ["!cast light"],
                "text": "The door opens.",
            }
        )
    ) == ["Old Oak", "The door opens."]


def test_long_fragments_are_segmented_without_word_loss():
    text = " ".join(["word"] * 800)
    pieces = list(fragments(text))
    assert " ".join(pieces) == text and all(len(p) <= 900 for p in pieces)


def test_one_overlong_segment_does_not_stop_other_examples():
    class Tokens:
        def encode(self, text, out_type):
            return text.split()

    class Translator:
        source = {"en-ru": Tokens()}

        def batch(self, texts, direction):
            return [("перевод:" + text, []) for text in texts]

    values = safe_batch(Translator(), ["short", " ".join(["long"] * 481), "next"], "en-ru")
    assert values[0][0] == "перевод:short" and values[2][0] == "перевод:next"
    assert values[1] == (None, ["SOURCE_SEGMENT_EXCEEDS_MODEL_CONTEXT"])


def test_structural_pass_alone_cannot_detect_a_wrong_game_term():
    # This actual failure class requires semantic review in addition to these checks.
    assert (
        diagnostics("The elemental becomes smaller.", "Элементарный становится меньше.", "en-ru")
        == []
    )


@pytest.mark.parametrize("limit", [None, 0, 321])
def test_known_failed_draft_backend_cannot_start_unbounded_bulk(tmp_path, limit):
    with pytest.raises(ValueError, match="bulk training translation is disabled"):
        run(tmp_path, tmp_path / "absent-model", limit=limit)


def test_missing_queue_cannot_be_reported_as_a_completed_translation(tmp_path):
    with pytest.raises(FileNotFoundError, match="translation queue"):
        run(tmp_path, tmp_path / "absent-model", limit=1)
