"""Shared normalisation for the small, explicitly supported command set."""


def normalise_action(action: str) -> str:
    return " ".join(action.casefold().split()).rstrip(".!?")


CHAT_TARGETS = {
    "беседа со стражником": "guard",
    "беседа с жительницей": "villager",
    "беседа с торговцем": "merchant",
}
NPC_CONTACTS = {"подойти к стражнику": "guard", "подойти к жительнице": "villager"}


def allowed_intents():
    from rpg_vkr.application import CHECK_COMMANDS, ROLL_COMMANDS
    from rpg_vkr.domain.combat import COMBAT_COMMANDS
    from rpg_vkr.domain.progression import PRACTICE_COMMANDS
    from rpg_vkr.domain.world import WORLD_COMMANDS

    return (
        WORLD_COMMANDS
        | COMBAT_COMMANDS
        | PRACTICE_COMMANDS
        | ROLL_COMMANDS
        | set(CHECK_COMMANDS)
        | set(CHAT_TARGETS)
        | set(NPC_CONTACTS)
        | {"помощь", "уточнить намерение"}
    )
