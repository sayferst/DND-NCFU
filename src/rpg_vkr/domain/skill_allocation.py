"""Bounded drafts and replayable, idempotent allocation commands."""

import re

from rpg_vkr.domain.d20_progression import SKILLS


def normalized(increments):
    if not isinstance(increments, dict) or not increments or len(increments) > len(SKILLS):
        raise ValueError("Выберите навыки для распределения.")
    if any(
        not isinstance(k, str) or k not in SKILLS or type(v) is not int or not 1 <= v <= 5
        for k, v in increments.items()
    ):
        raise ValueError("Неверное распределение навыков.")
    return sorted(increments.items())


def preview(progress, increments):
    result = progress
    index = len(progress.events)
    for skill, steps in normalized(increments):
        for _ in range(steps):
            result = result.train(skill, f"preview:{index}")
            index += 1
    return result


def commit(progress, increments, command_id, expected):
    pairs = normalized(increments)
    if not isinstance(command_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", command_id):
        raise ValueError("Неверный идентификатор распределения.")
    prefix = "allocation:" + command_id + ":"
    prior = [event for event in progress.events if event.event_id.startswith(prefix)]
    if prior:
        old = {}
        for event in prior:
            if event.kind != "skill":
                raise ValueError("Идентификатор занят другим событием.")
            old[event.subject] = old.get(event.subject, 0) + 1
        if sorted(old.items()) != pairs:
            raise ValueError("Этот запрос уже использован для другого распределения.")
        return progress
    if progress != expected:
        raise ValueError("Состояние героя изменилось. Отмените черновик и начните заново.")
    result = progress
    index = 0
    for skill, steps in pairs:
        for _ in range(steps):
            result = result.train(skill, prefix + str(index))
            index += 1
    return result
