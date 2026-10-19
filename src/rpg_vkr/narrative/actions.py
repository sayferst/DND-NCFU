"""Bounded, explicit action evidence, resolved before any prose request.

This is not a general Russian language parser. Ambiguity never grants an attack,
an item or an extra turn. Only the engine computes consequences.
"""

import re
from dataclasses import dataclass

from rpg_vkr.domain.combat import ACTORS, ATTACK_COMMANDS
from rpg_vkr.narrative.speech import unquoted

NOTES = {
    "loot_pending": "Обыск и получение добычи ещё не реализованы. Предметы не получены.",
    "theft_pending": "Кража яблок ещё не реализована. Яблоки не добавлены в инвентарь.",
    "single_attack": "Выполнена одна попытка удара. Следующий удар требует нового действия.",
    "attack_rules": (
        "Сила проверяет попадание; Ловкость — незамеченный подход, если он заявлен. "
        "Урон и ответ противника рассчитываются отдельно."
    ),
}
ATTACK = (
    r"\b(?:атаковать|атакую|напасть|нападу|нападаю|ударить|ударю|ударяю|вонзить|вонжу|"
    r"вонзаю|втыкаю|воткнуть|добить|добью|добиваю|убить|убью|убиваю|зарезать|зарежу)\b"
)
TARGETS = {
    "guard": r"стражник\w*|страж[ауем]",
    "villager": r"жительниц\w*|девушк\w*|женщин\w*",
    "merchant": r"торгов\w*|купец|купца|купцу",
    "wolf": r"волк\w*",
    "boar": r"кабан\w*",
}


@dataclass(frozen=True)
class ActionPlan:
    commands: tuple[str, ...] = ()
    target: str = ""
    notes: tuple[str, ...] = ()
    clarification: str = ""


def action_plan(session, text, *, allow_interactions=False):
    """Return None for conversation; a blocked plan must not go to the writer."""
    from rpg_vkr.narrative.dialogue import last_interlocutor

    value = unquoted(text)
    if not re.search(ATTACK, value):
        if re.match(r"(?:я\s+)?(?:хочу\s+)?(?:обыс\w*|заберу|забрать|украсть|украду)\b", value):
            if allow_interactions and not re.search(r"обыс|труп", value):
                return None
            return ActionPlan(
                clarification=(
                    "Обыск и кража пока не реализованы. Предметы не получены; мир не изменён."
                )
            )
        # A place is not a conversational addressee. Support two explicit steps.
        movement = re.fullmatch(
            r"(?:я\s+)?(?:хочу\s+)?(?:подойду|подойти|пойду|пойти|иду|идти)\s+"
            r"(?:к|в|на)\s+(воротам|ворота|рынок|дорогу)\s+и\s+"
            r"(?:осмотрюсь|осмотреться|оглянусь|оглядеться)(?:\s+вокруг)?",
            value,
        )
        if movement:
            move = {
                "воротам": "идти к воротам",
                "ворота": "идти к воротам",
                "рынок": "идти на рынок",
                "дорогу": "идти на дорогу",
            }[movement[1]]
            return ActionPlan((move, "осмотреться"))
        return None
    # Hypotheticals, quoted/reported speech, negations and threats are not attacks.
    if (
        "?" in text
        or re.match(r"(?:расскажи\w*|объясни\w*|опиши\w*|как\b|думаю\b|мечтаю\b)", value)
        or re.search(
            r"\b(?:если|могу ли|можно ли|что будет|цитирую|сказал\w*|снится|"
            r"скажу|говорю|спрошу|спрашиваю|спросить|угрожаю)\b",
            value,
        )
        or re.search(
            r"\b(?:не|без)\b", re.sub(r"\b(?:ничего не говоря|не буду сомневаться)\b", "", value)
        )
        or re.search(r"\b(?:тебя|вас)\s+(?:убью|зарежу|ударю)\b", value)
    ):
        return None
    lead = re.sub(r"^ничего не говоря[,\s]*", "", value)
    lead = re.sub(r"^(?:я\s+)?(?:(?:хочу|попробую|буду)\s+)?", "", lead)
    lead = re.sub(r"^(?:(?:скрытно|незаметно|тихо|молча)\s+)+", "", lead)
    if not re.match(
        ATTACK + r"|\b(?:достаю|достать|выну|возьму|взять|подбежать|подбегу|"
        r"обернуться|обернусь|подойти|подойду|подхожу|подкрасться)\b",
        lead,
    ):
        return None
    visible = [key for key in ACTORS if session.actor_is_here(key)]
    mentioned = [
        key for key, pattern in TARGETS.items() if re.search(r"\b(?:" + pattern + r")\b", value)
    ]
    from rpg_vkr.domain.director import known_facts
    from rpg_vkr.narrative.turn_brief import name_forms

    for (actor, key), name in known_facts(session.turns).items():
        if (
            key == "public_name"
            and actor in ACTORS
            and any(re.search(r"\b" + re.escape(form) + r"\b", value) for form in name_forms(name))
            and actor not in mentioned
        ):
            mentioned.append(actor)
    # Multiple named targets would require a tactical sequence, not an arbitrary first match.
    if len(mentioned) > 1:
        return ActionPlan(clarification="Укажите одну цель удара. Действие пока не выполнено.")
    target = mentioned[0] if mentioned else None
    if target is None:
        if not re.search(r"\b(?:ее|ей|ней|она|его|ему|ним|он)\b", value) and not re.fullmatch(
            r"(?:я\s+)?(?:хочу\s+)?" + ATTACK + r"(?:\s+(?:ножом|мечом|посохом|кулаком))?", value
        ):
            return ActionPlan(
                clarification=(
                    "Не удалось однозначно определить цель. Кого именно вы хотите атаковать?"
                )
            )
        if re.search(r"\b(?:ее|ей|ней|она)\b", value):
            candidates = [key for key in visible if key == "villager"]
        elif re.search(r"\b(?:его|ему|ним|он)\b", value):
            candidates = [key for key in visible if key != "villager"]
        else:
            candidates = visible
        previous = session.combat.active or last_interlocutor(session)
        target = (
            previous
            if previous in candidates
            else (candidates[0] if len(candidates) == 1 else None)
        )
    if not target:
        return ActionPlan(
            clarification="Кого вы хотите атаковать? Назовите одну цель рядом с вами."
        )
    if target not in visible:
        return ActionPlan(clarification="Названной цели здесь нет. Удар не выполнен.")
    owned = " ".join(item for item, _ in session.extra_items).casefold()
    for pattern, label in (
        (r"нож\w*|кинжал\w*", "нож"),
        (r"меч\w*", "меч"),
        (r"посох\w*", "посох"),
        (r"топор\w*", "топор"),
    ):
        if re.search(r"\b(?:" + pattern + r")\b", value) and not re.search(
            r"\b(?:" + pattern + r")\b", owned
        ):
            return ActionPlan(
                clarification=(
                    f"В инвентаре нет оружия «{label}». Удар не выполнен. "
                    "Проверьте инвентарь и выберите имеющееся оружие."
                )
            )
    command = next(key for key, actor in ATTACK_COMMANDS.items() if actor == target)
    commands = (command,)
    if re.search(r"незаметн|скрытн|подкра|тихо", value) and not session.combat.active:
        stealth = {
            "guard": "подкрасться к стражнику",
            "villager": "подкрасться к жительнице",
            "merchant": "подкрасться к торговцу",
            "wolf": "подкрасться к волку",
            "boar": "подкрасться к кабану",
        }[target]
        commands = (stealth, command)
    notes = []
    if re.search(r"обыс|труп|добыч|кошелек", value):
        notes.append("loot_pending")
    if re.search(r"яблок", value) and re.search(r"заб|возьм|взять|укра", value):
        notes.append("theft_pending")
    if len(re.findall(ATTACK, value)) > 1:
        notes.append("single_attack")
    if re.search(r"сил\w*", value) and re.search(r"ловк\w*", value):
        notes.append("attack_rules")
    return ActionPlan(commands, target, tuple(notes))
