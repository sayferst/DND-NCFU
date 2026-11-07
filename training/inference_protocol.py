"""Bounded tokenizer/generation protocol, testable without weights or Torch."""

from training.model_profiles import template_arguments


def stopping_tokens(tokenizer, config):
    values = []
    if tokenizer.eos_token_id is not None:
        values.append(tokenizer.eos_token_id)
    if config.get("model_family") == "faun_mistral_nemo":
        vocab = tokenizer.get_vocab()
        if "<|im_end|>" in vocab:
            values.append(vocab["<|im_end|>"])
    values = list(dict.fromkeys(values))
    if not values or any(type(v) is not int or v < 0 for v in values):
        raise ValueError("Tokenizer has no valid stopping token")
    return values


def prepare_inputs(body, tokenizer, config, device):
    if not isinstance(body, dict):
        raise ValueError("Request must be an object")
    messages = body.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 12:
        raise ValueError("Invalid messages")
    for message in messages:
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or message["role"] not in ("system", "user", "assistant")
            or not isinstance(message["content"], str)
            or not message["content"].strip()
            or len(message["content"]) > 64000
        ):
            raise ValueError("Invalid message role or content")
    options = body.get("options", {})
    if not isinstance(options, dict):
        raise ValueError("Invalid generation options")
    limit = options.get("num_predict", 1024)
    if type(limit) is not int or not 1 <= limit <= config.get("serving_max_output", 1024):
        raise ValueError("Output limit")
    context_limit = options.get("num_ctx", config.get("serving_context_limit", 4096))
    if type(context_limit) is not int or not 1 <= context_limit <= config.get(
        "serving_context_limit", 4096
    ):
        raise ValueError("Context limit")
    encoded = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
        **template_arguments(config),
    )
    inputs = {
        key: value.to(device)
        for key, value in encoded.items()
        if key in ("input_ids", "attention_mask")
    }
    if "input_ids" not in inputs or "attention_mask" not in inputs:
        raise ValueError("Tokenizer did not produce IDs and attention mask")
    length = inputs["input_ids"].shape[1]
    if length + limit > context_limit:
        raise ValueError("Prompt and requested output exceed context; no silent truncation")
    return inputs, length, limit, stopping_tokens(tokenizer, config)


def generate(body, tokenizer, model, config, torch):
    inputs, length, limit, stops = prepare_inputs(body, tokenizer, config, model.device)
    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=limit,
            do_sample=False,
            eos_token_id=stops,
            pad_token_id=tokenizer.pad_token_id
            if tokenizer.pad_token_id is not None
            else tokenizer.eos_token_id,
        )
    content = tokenizer.decode(output[0, length:], skip_special_tokens=True)
    return {
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop" if output[0, -1].item() in stops else "length",
        "prompt_eval_count": length,
        "eval_count": output.shape[1] - length,
    }
