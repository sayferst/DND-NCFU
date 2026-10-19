"""Read-only views of engine records. No dice, state changes or inferred world facts."""

from dataclasses import dataclass

from rpg_vkr.domain.character import ABILITY_NAMES, describe_check
from rpg_vkr.domain.combat import ACTORS, ATTACK_COMMANDS, STEALTH_COMMANDS, WEAPON_BASE
from rpg_vkr.domain.combat_math import counter_damage, hero_defence, player_damage


@dataclass(frozen=True)
class TurnPresentation:
    title: str
    story: str
    details: str = "Бросок не требуется."


def check_details(check, roll, purpose, *, graded=False):
    sign = "+" if check.modifier >= 0 else "−"
    outcome = (
        f"Для незамеченного подхода нужно {check.difficulty}. См. степени ниже."
        if graded
        else f"Нужно не меньше {check.difficulty}: " + ("успех." if check.succeeded else "неудача.")
    )
    return (
        f"Бросок №{roll.index} — {purpose}\n"
        f"Кубик (1–20): {roll.value}\n"
        f"{ABILITY_NAMES[check.ability]} {check.score}: бонус {check.modifier:+d}\n"
        f"Итого: {roll.value} {sign} {abs(check.modifier)} = {check.total}\n" + outcome
    )


def present_turn(turn) -> TurnPresentation:
    from rpg_vkr.narrative.actions import NOTES

    view = _present_turn(turn)
    if turn.notes:
        return TurnPresentation(
            view.title, view.story + "\n" + "\n".join(NOTES[n] for n in turn.notes), view.details
        )
    return view


def _present_turn(turn) -> TurnPresentation:
    if turn.interaction:
        record = turn.interaction
        details = "Изменения предметов и места применены одной проверенной цепочкой."
        if record.roll:
            details = (
                check_details(record.check, record.roll, "завладение чужим предметом")
                + "\n"
                + details
            )
        return TurnPresentation("Итог действия в мире", record.summary, details)
    if turn.challenge:
        from rpg_vkr.domain.challenge import CHALLENGES

        record = turn.challenge
        purpose = CHALLENGES[record.kind][2]
        title = ABILITY_NAMES[record.check.ability] + (
            " — успех" if record.check.succeeded else " — неудача"
        )
        return TurnPresentation(
            title,
            record.story(),
            check_details(record.check, record.roll, purpose) + "\nАвторская проверка попытки. "
            "Предметы, награды и переходы требуют отдельных правил.",
        )
    if turn.inspection:
        record = turn.inspection
        details = []
        for item in record.checks:
            purpose = (
                "длительный поиск: выносливость"
                if item.check.ability == "constitution"
                else "осмысленные детали окружения"
            )
            details.append(check_details(item.check, item.roll, purpose))
        details.append(
            "Авторское исследование: Телосложение поддерживает долгий "
            "поиск, но не заменяет понимание. Опыт/предметы не выдаются."
        )
        title = "Исследование — " + ("найдены зацепки" if record.clues else "новых зацепок нет")
        return TurnPresentation(title, record.story(), "\n\n".join(details))
    if turn.combat:
        return present_combat(turn)
    if turn.check is not None and turn.roll is not None:
        check = turn.check
        title = f"{ABILITY_NAMES[check.ability]} — " + ("успех" if check.succeeded else "неудача")
        # Strip only the exact engine-authored calculation prefix. Historic unknown
        # commands and arbitrary text are never interpreted as new game actions.
        prefix = describe_check(check, turn.roll.value)
        story = (
            turn.text.removeprefix(prefix).lstrip() if turn.text.startswith(prefix) else turn.text
        )
        return TurnPresentation(
            title,
            title + (".\n" + story if story else ". Это учебная проверка, мир не изменился."),
            check_details(check, turn.roll, "проверка характеристики"),
        )
    if turn.roll is not None:
        value = turn.roll.value
        return TurnPresentation(
            f"Кубик — {value}",
            f"На кубике выпало {value}. Сам по себе этот бросок не меняет мир.",
            f"Бросок №{turn.roll.index}\nКубик с 20 гранями: {value}.\n"
            "Бонусы не применялись. Проверки успеха и урона не было.",
        )
    return TurnPresentation("Без броска", turn.text)


def present_combat(turn) -> TurnPresentation:
    record = turn.combat
    result = record.outcome
    if not result.rolls:
        return TurnPresentation("Действие без броска", turn.text)
    command = record.command
    check = result.check
    rolls = iter(result.rolls)
    story, details = [], []
    title = "Итог действия"
    if command in STEALTH_COMMANDS:
        approach = next(rolls)
        details.append(check_details(check, approach, "скрытное приближение", graded=True))
        if check.total >= 15:
            title = "Незамеченный подход · следующая атака ×2"
            story.append(
                "Вы осторожно сокращаете расстояние, оставаясь незамеченным. "
                "Следующая попытка атаки получит удвоенный урон при попадании."
            )
        elif check.total >= 10:
            title = "Подход почти удался · вас заметили в конце"
            story.append("Почти у самой цели вас замечают. Скрытого удара не получится.")
        elif check.total >= 5:
            title = "Частичный успех · вас заметили на полпути"
            story.append("Вы проходите часть пути незаметно, но дальше цель обнаруживает вас.")
        else:
            title = "Неудачный подход · вас заметили сразу"
            story.append("Скрытно приблизиться не удалось. Цель замечает вас в начале подхода.")
        details.append(
            "Степени подхода по итоговой сумме:\n"
            "15 и выше — незамеченным; 10–14 — замечен в конце;\n"
            "5–9 — замечен на полпути; ниже 5 — замечен сразу.\n"
            "Порог 15 относится к полностью незамеченному подходу."
        )
    elif command in ATTACK_COMMANDS or command == "атаковать":
        hit = next(rolls)
        details.append(check_details(check, hit, "попадание"))
        if not check.succeeded:
            title = "Промах · урона нет"
            story.append("Ваш удар не достигает цели. Броска на силу удара не было.")
            if record.before.surprise:
                story.append("Неожиданность потеряна; удвоение следующему удару не переносится.")
        else:
            power = next(rolls)
            weapon = WEAPON_BASE[record.class_id]
            calculation = player_damage(
                weapon, record.character.strength, power.value, record.before.surprise
            )
            strength, bonus = calculation.strength, calculation.bonus
            multiplier, damage = calculation.multiplier, calculation.total
            title = ("Скрытая атака ×2" if multiplier == 2 else "Попадание") + f" · урон {damage}"
            story.append(
                "Удар достигает цели. "
                + ("Урон удвоен благодаря незамеченному подходу. " if multiplier == 2 else "")
            )
            if bonus == 0:
                story.append("Кубик не усилил удар; вклад силы и оружия сохранён.")
            else:
                story.append(
                    f"Удачный бросок усилил урон на {bonus} до удвоения."
                    if multiplier == 2
                    else f"Кубик усилил урон на {bonus}."
                )
            details.append(
                f"Бросок №{power.index} — усиление удара\n"
                f"Кубик (1–20): {power.value}\n"
                "Прибавка: 1–5 → 0; 6–10 → 1; 11–15 → 2; 16–20 → 3.\n"
                f"Прибавка этого броска: +{bonus}\n"
                f"Оружие: {weapon}; вклад Силы: {strength} (отрицательный бонус здесь равен 0).\n"
                f"База: {weapon} + {strength} = {weapon + strength}\n"
                f"Урон: ({weapon + strength} + {bonus}) × {multiplier} = {damage}.\n"
                + (
                    "×2 — за незамеченный подход, только для этой попытки."
                    if multiplier == 2
                    else "×1 — обычная атака, без удвоения."
                )
            )
    elif command in {"уклониться", "отступить"}:
        evade = next(rolls)
        details.append(
            check_details(check, evade, "отступление" if command == "отступить" else "уклонение")
        )
        if command == "отступить":
            title = "Успешное отступление" if check.succeeded else "Отступить не удалось"
            story.append(
                "Вы разрываете дистанцию и выходите из схватки. Отношение цели не изменилось."
                if check.succeeded
                else "Противник не позволяет отступить и отвечает атакой."
            )
        else:
            title = "Успешное уклонение" if check.succeeded else "Уклонение не удалось"
            story.append(
                "Вы избегаете ответной атаки, но сами не наносите удар."
                if check.succeeded
                else "Манёвр не спасает от ответной атаки. Своего удара в этот ход нет."
            )
    elif command == "использовать бинт":
        healed = min(4, record.world_before.max_hp - record.world_before.hp)
        title = f"Лечение · +{healed} здоровья"
        story.append(
            f"Вы перевязываете рану и восстанавливаете {healed} здоровья. "
            "На это ушёл один бинт и действие; противник отвечает."
        )
        details.append(
            "Лечение без кубика: до 4 здоровья, не выше максимума. "
            f"Восстановлено: {healed}. Бинтов потрачено: 1."
        )
    counter = next(rolls, None)
    if counter is not None:
        # Engine records already contain the checked hit result and applied damage.
        # Derive the outcome from recorded HP change, not a second simulation.
        name, _, _, _, attack_bonus, enemy_base, _ = ACTORS[result.actor_id]
        defence = hero_defence(record.character.dexterity)
        total = counter.value + attack_bonus
        details.append(
            f"Бросок №{counter.index} — ответ противника\n"
            f"Кубик (1–20): {counter.value}; бонус: {attack_bonus:+d}\n"
            f"Итого: {counter.value} + {attack_bonus} = {total}\n"
            f"Ваша защита: {defence}. " + ("Попадание." if total >= defence else "Промах.")
        )
        power = next(rolls, None)
        if power is None:
            story.append(f"{name}: ответный удар проходит мимо.")
        else:
            healed = (
                min(4, record.world_before.max_hp - record.world_before.hp)
                if command == "использовать бинт"
                else 0
            )
            lost = record.world_before.hp + healed - result.world.hp
            bonus = counter_damage(enemy_base, power.value).bonus
            story.append(f"{name}: ответный удар попал. Вы потеряли {lost} здоровья.")
            details.append(
                f"Бросок №{power.index} — сила ответного удара\n"
                f"Кубик (1–20): {power.value}\n"
                "Прибавка: 1–10 → 0; 11–20 → 1.\n"
                f"Урон: база {enemy_base} + прибавка {bonus} = {enemy_base + bonus}.\n"
                f"Потеряно здоровья: {lost} (не больше оставшегося)."
            )
    if result.victory:
        story.append(f"{turn.speaker}: противник повержен. Схватка завершена.")
    if result.world.hp == 0:
        story.append("Вы выбыли из схватки. Загрузите сохранение или создайте нового героя.")
    suffix = turn.text.removeprefix(result.text).strip()
    if suffix:
        story.append(suffix)
    return TurnPresentation(title, title + ".\n" + "\n".join(story), "\n\n".join(details))
