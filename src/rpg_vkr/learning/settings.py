"""Opt-in settings outside saves; preserve the existing RAG mode and unknown preferences."""

import json

from rpg_vkr.learning.library import atomic_json

DEFAULTS = {"mode": 0, "library": False, "memory": False, "templates": False}


def settings_path():
    from rpg_vkr.resources import data_directory

    return data_directory() / "learning.json"


def load(path=None):
    path = path or settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return dict(DEFAULTS)
    except (OSError, ValueError):
        return dict(DEFAULTS)
    result = dict(DEFAULTS)
    for key in ("library", "memory", "templates"):
        if type(raw.get(key)) is bool:
            result[key] = raw[key]
    if type(raw.get("mode")) is int and raw["mode"] in (0, 1, 2):
        result["mode"] = raw["mode"]
    return result


def update(changes, path=None):
    path = path or settings_path()
    if not isinstance(changes, dict) or set(changes) - set(DEFAULTS):
        raise ValueError("Неверные настройки библиотеки.")
    for key, value in changes.items():
        if key == "mode":
            if type(value) is not int or value not in (0, 1, 2):
                raise ValueError("Неверный режим поиска.")
        elif type(value) is not bool:
            raise ValueError("Переключатель должен быть логическим.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, ValueError):
        raw = {}
    atomic_json(path, raw | changes)
    return load(path)
