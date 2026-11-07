"""100 explicitly prescribed boundary cases; not played rolls or real campaign episodes."""

from copy import deepcopy
from dataclasses import asdict, replace

from rpg_vkr.domain import owner_rules as rules
from training.schema import digest

KINDS = (
    "death_save",
    "damage_at_zero",
    "massive_damage",
    "nonlethal",
    "stabilize",
    "heal_unconscious",
    "heal_dead",
    "overcast_hp",
    "overcast_exhaustion",
    "overcast_insufficient_hp",
    "exhaustion_six",
    "long_rest",
    "short_rest",
    "natural_one",
    "natural_twenty",
    "unsupported_flight",
    "unknown_magic",
    "agreement_known",
    "agreement_unknown",
    "payment_choice_missing",
)


def compile_case(kind, variant):
    from training.grounded_curriculum import SCHEMA, changes, clean_prose, initial

    if kind not in KINDS or type(variant) is not int or not 0 <= variant < 5:
        raise ValueError("Unknown prescribed boundary case")
    face = (1, 9, 10, 19, 20)[variant]
    source = {
        "id": f"edge_{kind}_{variant}",
        "family": "owner_rule_boundaries",
        "condition_type": variant,
        "context": (
            "Явно синтетический граничный случай; D20 задан для проверки "
            "правила, а не выдан за сыгранный бросок."
        ),
        "action": kind,
        "synthetic": True,
        "source": "OWNER_AUTHORIZED_CURATED_RULE_BOUNDARY",
    }
    spec = {
        "operation": "boundary",
        "subject": "взрослый участник приключения",
        "goal": kind,
        "task": "strength",
        "success": "",
        "partial": "",
        "failure": "",
        "parameters": {},
    }
    before = initial(source, spec)
    before["hero"]["abilities"] = dict.fromkeys(before["hero"]["abilities"], 10)
    before["hero"]["life"] = asdict(rules.Life(8, 12))
    before["hero"]["mp"] = 0
    before["hero"]["mp_cap"] = 5
    before["facts"].update(
        resolver_actor="system", species="human", age_group="adult", boundary_kind=kind
    )
    life = rules.Life(8, 12)
    if kind in ("death_save", "damage_at_zero", "heal_unconscious", "stabilize"):
        life = rules.Life(0, 12, failures=2 if variant in (0, 3) and kind == "death_save" else 0)
    elif kind == "heal_dead":
        life = rules.Life(0, 12, dead=True)
    elif kind == "overcast_hp":
        life = rules.Life(2 * ((variant % 3) + 1), 12)
    elif kind == "overcast_insufficient_hp":
        life = rules.Life(1 + variant % 3, 12)
    elif kind in ("exhaustion_six", "overcast_exhaustion"):
        life = rules.Life(8, 12, exhaustion=4 + variant % 2)
    elif kind == "long_rest":
        life = rules.Life(8, 12, exhaustion=1 + variant % 4)
    before["hero"]["life"] = asdict(life)
    if kind.startswith("overcast") or kind == "payment_choice_missing":
        before["hero"]["known_effects"] = ["heal"]
        spec["task"] = "arcana"
    if kind.startswith("agreement"):
        spec["task"] = "persuasion"
    if kind == "death_save":
        spec["task"] = "death_save"
    after = deepcopy(before)
    new = life
    result = {
        "provenance": "SYNTHETIC_REFERENCE_EXECUTION",
        "rules_version": rules.VERSION,
        "operation": "boundary",
        "boundary_kind": kind,
        "subject_id": "hero",
        "goal": kind,
        "attempt_possible": True,
        "goal_reachable": True,
        "d20_required": False,
        "roll": None,
        "outcome": "success",
        "die_source": "PRESCRIBED_BOUNDARY_NOT_PLAYED_ROLL",
    }
    record = {}
    action = ""
    answer = ""
    if kind == "death_save":
        action = "Разреши спасбросок смерти по подтверждённому состоянию."
        new = rules.death_save(life, face)
        result.update(
            d20_required=True,
            roll={
                "natural": face,
                "total": face,
                "dc": 10,
                "succeeded": face >= 10,
                "outcome": "death_save",
                "complication": face == 1,
            },
        )
        answer = f"На D20 выпало{face}. " + (
            "Последний вдох затихает: три провала означают смерть."
            if new.dead
            else "Ты приходишь в сознание с1HP; счётчики смерти сброшены."
            if new.hp
            else "Цель стабильна при0HP; спасброски больше не нужны, пока не появится новый урон."
            if new.stable
            else (
                f"Сейчас успехов{new.successes}, провалов{new.failures}; при0HP "
                f"ты остаёшься без сознания."
            )
        )
    elif kind in ("damage_at_zero", "massive_damage", "nonlethal"):
        amount = (
            (1, 2, 5, 11, 12)[variant]
            if kind == "damage_at_zero"
            else (19, 20, 21, 24, 30)[variant]
            if kind == "massive_damage"
            else (8, 9, 12, 20, 30)[variant]
        )
        critical = variant % 2 == 1
        action = "Опиши подтверждённое попадание и состояние цели после урона."
        new = rules.damage(life, amount, critical=critical, nonlethal=kind == "nonlethal")
        record = {
            "damage": amount,
            "critical_hit": critical,
            "nonlethal_melee": kind == "nonlethal",
        }
        answer = f"Подтверждён урон{amount}. " + (
            "Цель мертва: выполнено условие мгновенной смерти."
            if new.dead
            else "Цель оглушена при0HP и сразу стабильна; спасброски смерти пока не требуются."
            if new.stable
            else f"При0HP получено провалов спасброска смерти: {new.failures}."
            if new.hp == 0
            else f"У цели осталось{new.hp}HP."
        )
    elif kind in ("stabilize", "heal_unconscious", "heal_dead"):
        action = (
            "Опиши результат первой помощи."
            if kind == "stabilize"
            else "Опиши результат обычного лечения цели."
        )
        if kind == "stabilize":
            new = rules.stabilize(life)
        else:
            new = rules.heal(life, variant + 1)
        record = {"healing": 0 if kind == "stabilize" else variant + 1}
        answer = (
            (
                "Первая помощь стабилизировала цель при0HP. Она остаётся без "
                "сознания; лечение не выполнено."
            )
            if kind == "stabilize"
            else (
                "Обычное лечение не вернуло умершего к жизни. Для этого нужен "
                "отдельный известный эффект воскрешения."
            )
            if new.dead
            else (
                f"Восстановлено{new.hp}HP. Цель приходит в сознание; счётчики "
                f"спасбросков смерти сброшены."
            )
        )
    elif kind in (
        "overcast_hp",
        "overcast_exhaustion",
        "overcast_insufficient_hp",
        "payment_choice_missing",
    ):
        action = (
            "Разреши только оплату и Аркану при перерасходе известного исцеления "
            "стоимостью3MP. Сам эффект заклинания пока не разрешай."
        )
        missing = (variant % 3) + 1 if kind in ("overcast_hp", "overcast_exhaustion") else 2
        before["hero"]["mp"] = after["hero"]["mp"] = 3 - missing
        result.update(spell_id="heal", spell_cost_mp=3, phase="payment_and_arcana_only")
        payment = (
            "exhaustion"
            if kind == "overcast_exhaustion"
            else None
            if kind == "payment_choice_missing"
            else "hp"
        )
        before["facts"]["overcast_payment_choice"] = payment
        after["facts"]["overcast_payment_choice"] = payment
        try:
            paid, record = rules.overcast(life, 3 - missing, 3, payment)
            check = rules.check(face, 0, record["dc"], exhaustion=life.exhaustion, partial=False)
            new = paid
            after["hero"]["mp"] = 0
            result.update(d20_required=True, roll=check, outcome=check["outcome"])
            answer = (
                f"На D20 выпало{face}; итог{check['total']} при сложности{record['dc']}. "
                + (
                    "Проверка перенапряжения пройдена; сам эффект ещё не разрешён."
                    if check["succeeded"]
                    else "Заклинание не сработало, но цена попытки остаётся."
                )
                + (
                    f" Уплачено{record['hp_spent']}HP."
                    if payment == "hp"
                    else f" Цена —{record['exhaustion_added']} уровня истощения."
                )
                + (
                    " При0HP ты теряешь сознание."
                    if new.hp == 0 and not new.dead
                    else " Шестой уровень истощения означает смерть."
                    if new.dead
                    else ""
                )
            )
        except ValueError:
            result.update(
                outcome="clarification_required" if payment is None else "goal_unreachable",
                goal_reachable=None if payment is None else False,
            )
            answer = (
                "Нужно явно выбрать оплату здоровьем или истощением. До этого броска и расхода нет."
                if payment is None
                else (
                    f"Требуется4HP, но сейчас есть{life.hp}HP. Оплата здоровьем "
                    f"недоступна; можно отдельно выбрать истощение, но этот выбор ещё "
                    f"не сделан."
                )
            )
    elif kind in ("exhaustion_six", "long_rest", "short_rest"):
        action = (
            "Опиши накопление истощения."
            if kind == "exhaustion_six"
            else "Опиши последствия завершённого отдыха."
        )
        if kind == "exhaustion_six":
            new = rules.add_exhaustion(life, 2)
            answer = "Достигнут шестой уровень истощения. Это смерть, а не обычная потеря сознания."
        elif kind == "long_rest":
            new = rules.long_rest(life)
            after["hero"]["mp"], after["hero"]["st"] = (
                after["hero"]["mp_cap"],
                after["hero"]["st_cap"],
            )
            answer = (
                f"Длительный отдых завершён; здоровье восстановлено до{new.hp}HP. "
                f"Истощение снизилось с{life.exhaustion} до{new.exhaustion}, то "
                f"есть на один уровень."
            )
        else:
            before["hero"]["life"]["exhaustion"] = 2
            after["hero"]["life"]["exhaustion"] = 2
            life = replace(life, exhaustion=2)
            new = life
            answer = (
                "Короткий отдых завершён. Два уровня обычного истощения "
                "сохраняются; такой отдых их не снимает."
            )
    elif kind in ("natural_one", "natural_twenty"):
        action = "Разреши допустимую проверку, не расширяя физические возможности."
        natural = 1 if kind == "natural_one" else 20
        before["hero"]["abilities"]["strength"] = 20 if natural == 1 else 1
        after["hero"]["abilities"] = deepcopy(before["hero"]["abilities"])
        check = rules.check(natural, 5 if natural == 1 else -5, 5 if natural == 1 else 30)
        result.update(d20_required=True, roll=check, outcome=check["outcome"])
        answer = (
            (
                "Натуральная1 дала итог6 против сложности5: основная цель "
                "достигнута с осложнением. Потеря темпа учтена, невозможных "
                "свойств не появилось."
            )
            if natural == 1
            else (
                "Натуральная20 даёт лучший физически допустимый результат этой "
                "попытки. Итог15 сохранён как настоящий расчёт; отсутствующих "
                "ресурсов и способностей нет."
            )
        )
    elif kind in ("unsupported_flight", "unknown_magic"):
        action = "Пытаюсь получить неподтверждённый эффект от обычного предмета."
        result.update(outcome="goal_unreachable", goal_reachable=False)
        answer = (
            "Обычный предмет не дал неподтверждённого эффекта. Бросок не "
            "создаёт отсутствующую способность, новых ресурсов нет."
        )
    elif kind in ("agreement_known", "agreement_unknown"):
        action = "Предлагаю NPC выполнимое соглашение в пределах известных полномочий."
        eligibility = rules.agreement_eligibility(
            authority=True if kind == "agreement_known" else None, feasible=True, constraints=[True]
        )
        before["npc"]["authority"] = True if kind == "agreement_known" else None
        after["npc"]["authority"] = before["npc"]["authority"]
        if eligibility == "eligible":
            check = rules.check(face, 2, 10, partial=False)
            before["hero"]["abilities"]["charisma"] = 14
            after["hero"]["abilities"]["charisma"] = 14
            result.update(d20_required=True, roll=check, outcome=check["outcome"])
            after["npc"]["agreement"] = check["succeeded"]
            answer = "Полномочия, выполнимость и жизненно важные ограничения проверены. " + (
                "Убеждение удалось: NPC принимает соглашение; ресурсы ещё не переданы."
                if check["succeeded"]
                else "Убеждение не удалось; соглашения и передачи ресурсов нет."
            )
        else:
            result.update(outcome="clarification_required", goal_reachable=None)
            answer = (
                "Полномочия NPC неизвестны. Сначала нужно уточнить, вправе ли он "
                "принять условия; высокий бросок не заменяет этот факт."
            )
    after["hero"]["life"] = asdict(new)
    after["world"]["minute"] += 480 if kind == "long_rest" else 60 if kind == "short_rest" else 1
    if result["roll"] and result["roll"].get("complication") and kind != "death_save":
        after["world"]["minute"] += 1
    result.update(
        details=record,
        changes=changes(before, after),
        before_sha256=digest(before),
        after_sha256=digest(after),
        duration_minutes=after["world"]["minute"] - before["world"]["minute"],
    )
    source["action"] = action
    return {
        "schema_version": SCHEMA,
        "sample_id": source["id"],
        "campaign_id": "edge:" + kind,
        "scene_mode": "grounded_narration",
        "synthetic": True,
        "human_reviewed": False,
        "source_scenario": source,
        "spec": spec,
        "seed": None,
        "public_context": {"source_context": source["context"], "state": before},
        "player_message": action,
        "engine_receipt": result,
        "assistant_reply": clean_prose(answer),
        "after_state": after,
        "review": {"method": "CURATED_RULE_BOUNDARY_AND_SHARED_MATH", "human_approval": False},
    }


def rows():
    return [compile_case(kind, variant) for kind in KINDS for variant in range(5)]
