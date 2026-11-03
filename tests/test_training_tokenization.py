"""Pre-GPU failures, assistant-only supervision, and explicit tokenizer API contract."""

import hashlib
import json
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_training_pipeline import sample

from training.tokenize_dataset import encode_dataset, encode_rows, verify_cpu_report
from training.train_lora import run_signature, train, validate_resume


class CharacterTokenizer:
    pad_token_id = 0
    eos_token_id = 3

    def apply_chat_template(
        self, messages, *, tokenize, add_generation_prompt, return_dict=True, **kwargs
    ):
        # Transformers5 defaults to BatchEncoding. The encoder must explicitly request IDs.
        assert tokenize is True and return_dict is False
        text = "".join(m["role"] + ":" + m["content"] + "\n" for m in messages)
        if add_generation_prompt:
            text += "assistant:"
        return [ord(c) for c in text]

    def __call__(self, text, *, add_special_tokens):
        assert add_special_tokens is False
        return {"input_ids": [ord(c) for c in text]}


def corpus(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    hashes = {}
    for i, name in enumerate(("train", "val", "test")):
        raw = (json.dumps(sample(i, str(i)), ensure_ascii=False) + "\n").encode()
        (root / (name + ".jsonl")).write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    manifest = {
        "status": "READY",
        "privacy_review_confirmed": True,
        "sha256": "authored-fixture",
        "file_sha256": hashes,
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return {
        "dataset": str(root),
        "dataset_sha256": "authored-fixture",
        "max_length": 2048,
        "model_family": "faun_mistral_nemo",
        "model_path": str(tmp_path / "model"),
        "output": str(tmp_path / "out"),
    }


def test_only_assistant_completion_has_supervised_labels():
    row = sample(1, "a")
    encoded, stats = encode_rows(
        CharacterTokenizer(), [row], {"model_family": "faun_mistral_nemo", "max_length": 2048}
    )
    entry = encoded[0]
    n = stats[0]["prompt"]
    assert entry["labels"][:n] == [-100] * n
    assert entry["labels"][n:] == [ord(c) for c in row["assistant_reply"] + "\n"]
    assert len(entry["input_ids"]) == len(entry["labels"]) == len(entry["attention_mask"])
    assert all(entry["attention_mask"])


def test_legacy_qwen_answer_eos_and_thinking_flag_preserved():
    class QwenTokenizer(CharacterTokenizer):
        def apply_chat_template(self, *args, **kwargs):
            assert kwargs["enable_thinking"] is False
            return super().apply_chat_template(*args, **kwargs)

    row = sample(1, "q")
    values, _ = encode_rows(QwenTokenizer(), [row], {"max_length": 2048})
    assert values[0]["labels"][-1] == 3


def test_all_overlength_ids_reported_without_silent_drop():
    with pytest.raises(ValueError, match="no silent dropping: 1, 2"):
        encode_rows(CharacterTokenizer(), [sample(1, "a"), sample(2, "b")], {"max_length": 4})


@pytest.mark.parametrize("token", ["<|im_start|>", "<|im_end|>", "<s>", "</s>"])
def test_chat_delimiters_in_player_or_reply_cannot_enter_training(token):
    row = sample(1, "a")
    row["player_message"] += token
    with pytest.raises(ValueError, match="control token"):
        encode_rows(CharacterTokenizer(), [row], {"max_length": 2048})


def test_changed_chat_prefix_cannot_silently_shift_loss_mask():
    class WrongTemplate(CharacterTokenizer):
        def apply_chat_template(self, *args, **kwargs):
            result = super().apply_chat_template(*args, **kwargs)
            return result if kwargs["add_generation_prompt"] else [9] + result

    with pytest.raises(ValueError, match="generation prefix"):
        encode_rows(
            WrongTemplate(),
            [sample(1, "a")],
            {"model_family": "faun_mistral_nemo", "max_length": 2048},
        )


def test_all_splits_checked_and_cpu_report_bound_to_token_ids(tmp_path):
    c = corpus(tmp_path)
    _, report = encode_dataset(c, CharacterTokenizer())
    assert set(report["splits"]) == {"train", "val", "test"}
    assert report["training_steps"] == 0 and report["dropped_samples"] == 0
    path = tmp_path / "cpu.json"
    raw = json.dumps(report).encode()
    path.write_bytes(raw)
    c.update(
        cpu_tokenization_report=str(path),
        cpu_tokenization_report_sha256=hashlib.sha256(raw).hexdigest(),
    )
    verify_cpu_report(c, report)
    changed = deepcopy(report)
    changed["splits"]["train"]["encoded_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="GPU tokenizer differs"):
        verify_cpu_report(c, changed)
    path.write_text("{}")
    with pytest.raises(ValueError, match="CPU report changed"):
        verify_cpu_report(c, report)


def test_changed_validation_data_prevents_encoding(tmp_path):
    c = corpus(tmp_path)
    from pathlib import Path

    (Path(c["dataset"]) / "val.jsonl").write_text("{}")
    with pytest.raises(ValueError, match="split changed"):
        encode_dataset(c, CharacterTokenizer())


def test_bad_data_rejected_before_model_weight_allocation(tmp_path, monkeypatch):
    c = corpus(tmp_path)
    c.update(model_family="legacy_qwen", max_length=1)
    model_loads = []

    def allocate(*args, **kwargs):
        model_loads.append(True)
        raise AssertionError("Weights must not be loaded for invalid data")

    import training.train_lora as module

    monkeypatch.setattr(
        module, "preflight", lambda _: "READY"
    )  # Only the hardware gate is simulated.
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "peft",
        SimpleNamespace(LoraConfig=None, get_peft_model=None, prepare_model_for_kbit_training=None),
    )
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(
            AutoModelForCausalLM=SimpleNamespace(from_pretrained=allocate),
            AutoTokenizer=SimpleNamespace(
                from_pretrained=lambda *args, **kwargs: CharacterTokenizer()
            ),
            BitsAndBytesConfig=None,
            DataCollatorForSeq2Seq=None,
            Trainer=None,
            TrainingArguments=None,
        ),
    )
    with pytest.raises(ValueError, match="overlength"):
        train(c)
    assert not model_loads and not (tmp_path / "out").exists()


def test_smoke_checkpoint_cannot_resume_as_full_run(tmp_path):
    output = tmp_path / "run"
    checkpoint = output / "checkpoint-2"
    checkpoint.mkdir(parents=True)
    c = {"output": str(output)}
    (output / "run-provenance.json").write_text(
        json.dumps({"config_sha256": run_signature(c), "smoke": True})
    )
    (checkpoint / "trainer_state.json").write_text('{"global_step":2}')
    assert validate_resume(c, checkpoint, smoke=True) == str(checkpoint)
    with pytest.raises(ValueError, match="smoke/full"):
        validate_resume(c, checkpoint, smoke=False)
