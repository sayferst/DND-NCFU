"""Exact hash-pinned template backend, shared with the existing CPU implementation."""

import hashlib
from pathlib import Path

from training.fetch_faun_tokenizer import HASHES

FAUN_TEMPLATE_SHA = HASHES["chat_template.jinja"]


class PinnedFaunTokenizer:
    """Lightweight tokenizer.json backend; render only the hash-pinned ChatML template.

    This deliberately implements that single public template verbatim, without
    executing Jinja supplied by a dataset. GPU training also checks this backend's
    IDs against AutoTokenizer before loading weights.
    """

    def __init__(self, root, config):
        from tokenizers import Tokenizer

        root = Path(root)
        if config.get("model_family") != "faun_mistral_nemo":
            raise ValueError("Lightweight CPU tokenizer supports the pinned Faun profile only")
        raw = (root / "chat_template.jinja").read_bytes()
        if (
            hashlib.sha256(raw).hexdigest() != FAUN_TEMPLATE_SHA
            or config.get("chat_template_sha256") != FAUN_TEMPLATE_SHA
        ):
            raise ValueError("BLOCKED_MODEL: pinned Faun ChatML template differs")
        for name, expected in HASHES.items():
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
                raise ValueError("BLOCKED_MODEL: pinned tokenizer metadata changed: " + name)
        self.backend = Tokenizer.from_file(str(root / "tokenizer.json"))
        self.fingerprint = {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("tokenizer.json", "chat_template.jinja")
        }

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, return_dict=False):
        text = "".join(
            "<|im_start|>" + m["role"] + "\n" + m["content"] + "<|im_end|>\n" for m in messages
        )
        # Transformers renders this template with trim_blocks=True/lstrip_blocks=True.
        if add_generation_prompt:
            text += "<|im_start|>assistant\n"
        return self.backend.encode(text, add_special_tokens=False).ids if tokenize else text
