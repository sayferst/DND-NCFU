"""Editable storyteller instructions, read as data for each new request."""

import hashlib
from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[3] / "prompts"
DEFAULT_PATH = PROMPTS / "master_system_prompt.txt"
LOCAL_PATH = PROMPTS / "master_system_prompt.local.txt"
MAX_BYTES = 65536
MAX_CHARACTERS = 24000


def load_instructions(*, default_path=None, local_path=None):
    default_path = DEFAULT_PATH if default_path is None else Path(default_path)
    local_path = LOCAL_PATH if local_path is None else Path(local_path)
    path = local_path if local_path.exists() else default_path
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Файл инструкции слишком большой.")
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise ValueError("Не удалось прочитать инструкцию мастера в UTF-8: " + path.name) from error
    if not text.strip() or len(text) > MAX_CHARACTERS:
        raise ValueError("Инструкция мастера пуста или превышает 24000 символов.")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
        raise ValueError("В инструкции мастера есть недопустимые управляющие символы.")
    return text.replace("\r\n", "\n").strip()


def instruction_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
