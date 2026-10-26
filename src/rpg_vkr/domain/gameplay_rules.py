"""Explicit version dispatch; a newer catalog never rebalances an older campaign."""

from rpg_vkr.domain import gameplay as v1


def revision(state):
    from rpg_vkr.domain import gameplay_v2 as v2

    versions = {v1.VERSION: 1, v2.VERSION: 2}
    if not isinstance(state, dict) or state.get("version") not in versions:
        raise ValueError("Неизвестная версия игрового обработчика.")
    return versions[state["version"]]


def initial(identity, character, *, revision=1):
    if type(revision) is not int:
        raise ValueError("Версия должна быть целым числом.")
    if revision == 1:
        return v1.initial(identity, character)
    if revision == 2:
        from rpg_vkr.domain import gameplay_v2 as v2

        return v2.initial(identity, character)
    raise ValueError("Неизвестная версия новых правил.")


def restore_initial(identity, character, state, schema):
    rev = revision(state)
    if schema != 23 + rev:
        raise ValueError("Схема не соответствует версии игровых правил.")
    return initial(identity, character, revision=rev)


def execute(state, command, args, context, dice):
    if revision(state) == 1:
        return v1.execute(state, command, args, context, dice)
    from rpg_vkr.domain import gameplay_v2 as v2

    return v2.execute(state, command, args, context, dice)
