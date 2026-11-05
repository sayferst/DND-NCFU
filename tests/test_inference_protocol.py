"""Protocol tests use fake tensors/models; no weights, actual generation, or CUDA claims."""

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from training.inference_protocol import generate, prepare_inputs, stopping_tokens
from training.train_lora import smoke_samples, validate_losses


class Tensor:
    def __init__(self, values):
        self.values = values
        self.shape = (1, len(values))

    def to(self, device):
        assert device == "test-device"
        return self

    def __getitem__(self, key):
        row, index = key
        assert row == 0
        if isinstance(index, slice):
            return self.values[index]
        return SimpleNamespace(item=lambda: self.values[index])


class Tokenizer:
    eos_token_id = 2
    pad_token_id = 0

    def get_vocab(self):
        return {"<|im_end|>": 7}

    def apply_chat_template(self, messages, **kwargs):
        assert kwargs["return_dict"] is True and kwargs["return_tensors"] == "pt"
        return {"input_ids": Tensor([1, 4, 5]), "attention_mask": Tensor([1, 1, 1])}

    def decode(self, tokens, *, skip_special_tokens):
        assert skip_special_tokens and tokens == [8, 7]
        return "Подтверждённый результат."


def body():
    return {
        "model": "dnd-trained-narrator",
        "messages": [{"role": "user", "content": "Опиши результат."}],
        "options": {"num_predict": 8, "num_ctx": 64},
    }


def config():
    return {"model_family": "faun_mistral_nemo", "serving_context_limit": 64}


def test_chatml_stop_and_attention_mask_passed_as_model_keywords():
    captured = {}

    def inference(**kwargs):
        captured.update(kwargs)
        return Tensor([1, 4, 5, 8, 7])

    model = SimpleNamespace(device="test-device", generate=inference)
    result = generate(body(), Tokenizer(), model, config(), SimpleNamespace(no_grad=nullcontext))
    assert "input_ids" in captured and "attention_mask" in captured
    assert captured["eos_token_id"] == [2, 7] and captured["pad_token_id"] == 0
    assert result["done_reason"] == "stop" and result["eval_count"] == 2
    assert result["message"]["content"] == "Подтверждённый результат."


@pytest.mark.parametrize(
    "change",
    [
        {"messages": []},
        {"messages": [{"role": "tool", "content": "x"}]},
        {"messages": [{"role": "user", "content": ""}]},
        {"options": {"num_predict": False}},
        {"options": {"num_predict": 0}},
        {"options": {"num_predict": 100, "num_ctx": 64}},
        {"options": {"num_predict": 8, "num_ctx": 2}},
    ],
)
def test_invalid_requests_fail_before_generation(change):
    with pytest.raises(ValueError):
        prepare_inputs(body() | change, Tokenizer(), config(), "test-device")


def test_legacy_model_uses_eos_without_assuming_chatml_stop():
    assert stopping_tokens(Tokenizer(), {}) == [2]


def test_smoke_exercises_maximum_length_and_never_changes_input():
    rows = [{"input_ids": [1] * n} for n in (7, 100, 17, 50, 24)]
    selected = smoke_samples(rows)
    assert [len(r["input_ids"]) for r in selected] == [100, 24]
    assert [len(r["input_ids"]) for r in rows] == [7, 100, 17, 50, 24]
    with pytest.raises(ValueError):
        smoke_samples([])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_paid_training_stops_on_nonfinite_loss(bad):
    validate_losses({"loss": 1.2, "eval_loss": 1.4})
    with pytest.raises(ValueError, match="Non-finite"):
        validate_losses({"loss": bad})


def test_paired_comparison_rejects_same_ids_with_different_prompts(tmp_path):
    from training.compare_models import compare

    paths = []
    for condition, prompt in (("faun_base", "one"), ("faun_trained", "two")):
        path = tmp_path / (condition + ".json")
        path.write_text(
            json.dumps(
                {
                    "condition": condition,
                    "model_revision": "fixture",
                    "actual_inference": True,
                    "dataset_sha256": "corpus",
                    "samples": [
                        {
                            "id": "holdout",
                            "family": "test",
                            "prompt_sha256": prompt,
                            "critical_violations": [],
                            "latency_seconds": 1,
                        }
                    ],
                }
            )
        )
        paths.append(path)
    with pytest.raises(ValueError, match="identical prompts"):
        compare(paths)
