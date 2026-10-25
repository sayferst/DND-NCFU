"""Journal-only palettes; colour choices never change message authority."""

import re

DARK_FANTASY = {
    "background": "#171A21",
    "narrator": "#E8DFC9",
    "player": "#A5C9F2",
    "npc": "#C7A9E8",
    "system": "#AAB4C3",
    "important": "#E8BE77",
    "hostile": "#E7A1A1",
    "success": "#A3D4B5",
    "secondary": "#B8B1A5",
}
PRESETS = {
    "Тёмное фэнтези": DARK_FANTASY,
    "Древний пергамент": {
        "background": "#F0E5CC",
        "narrator": "#382D24",
        "player": "#234C70",
        "npc": "#653768",
        "system": "#514B43",
        "important": "#754513",
        "hostile": "#842F35",
        "success": "#285936",
        "secondary": "#635443",
    },
    "Магический обсидиан": {
        "background": "#12121C",
        "narrator": "#D9DCE8",
        "player": "#A8C8FF",
        "npc": "#C6B0F5",
        "system": "#ADB5CA",
        "important": "#D9BCF8",
        "hostile": "#F0A4AC",
        "success": "#A3D9CB",
        "secondary": "#B0ABC0",
    },
}
LABELS = {
    "background": "Фон",
    "narrator": "Мастер",
    "player": "Герой",
    "npc": "Речь NPC",
    "system": "Система",
    "important": "Важные события / заголовки",
    "hostile": "Опасность / урон",
    "success": "Успех",
    "secondary": "Подписи",
}


def journal_palette(preset, overrides=None):
    if preset not in PRESETS:
        raise ValueError("Неизвестная тема журнала.")
    overrides = {} if overrides is None else overrides
    if not isinstance(overrides, dict) or set(overrides) - set(DARK_FANTASY):
        raise ValueError("Неверные поля цветов журнала.")
    if any(
        not isinstance(v, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", v)
        for v in overrides.values()
    ):
        raise ValueError("Цвет должен иметь формат #RRGGBB.")
    return {**PRESETS[preset], **overrides}
