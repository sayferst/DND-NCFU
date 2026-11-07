"""Generate declared-scenario reference executions and original narrative demonstrations."""

import argparse
import hashlib
import json
import random
from copy import deepcopy
from pathlib import Path

from training.faun_v5.content import ITEMS, NAMES, PLACES, TEMPERAMENTS
from training.faun_v5.narrative import PLANS, render, request
from training.faun_v5.rules import resolve

SEED = 37
SYSTEM = (
    "Ты мастер фэнтезийной настольной игры. Отвечай по-русски естественно и ясно. "
    "Применяй только явно указанные правила сценария. Если дан engine_result, он определяет "
    "достоверный исход. Отделяй намерение от выполненного действия; не принимай решений за игрока. "
    "Не добавляй предметы, ресурсы, способности, тайные знания и постоянные эффекты. "
    "Различай неизвестный факт и ложный факт. Передавай голос и интересы NPC из данных сцены. "
    "Темп зависит от задачи: простой расчёт краток, значимый разговор может быть развёрнутым."
)
RULES = {
    "damage_zero": (
        "Урон больше 0 при 0 HP снимает стабильность и даёт один провал "
        "спасброска смерти, критический — два. Три провала или урон не "
        "меньше максимума HP означают смерть. HP остаётся 0."
    ),
    "stabilize": (
        "Успешная проверка Медицины стабилизирует живую цель при 0 HP: "
        "счётчики спасбросков смерти обнуляются, здоровье не "
        "восстанавливается, сознание не возвращается."
    ),
    "overcast": (
        "Домашнее R10: нехватка не более 3 MP; только с явным "
        "согласием. Недостающее оплачивается полностью: 2 HP за MP "
        "(вплоть до 0 HP, без сознания) либо ceil(нехватка/2) уровней "
        "истощения. Шестой уровень смертелен. Все цены сохраняются при "
        "провале. Без знания заклинания или при нехватке полной цены HP "
        "попытка блокируется."
    ),
    "social": (
        "R14: успешное убеждение обязывает NPC согласиться только при "
        "известных полномочиях и жизненно важных ограничениях, "
        "выполнимой просьбе и соблюдении этих ограничений. Неизвестное "
        "сначала уточняется. Высокий бросок не создаёт полномочий и "
        "ресурсов."
    ),
    "catalog_lookup": (
        "Достоверны только название, категория и ID предоставленной "
        "индексной записи. Не выводи свойства из названия; прямое "
        "обращение к исходной SQLite здесь не выполнялось."
    ),
    "attack": (
        "Атака попадает при сумме броска и модификатора не ниже КБ; при "
        "промахе урон равен нулю. Натуральные критические исходы здесь "
        "не используются."
    ),
    "save": "Спасбросок успешен при сумме не ниже сложности.",
    "skill": "Проверка успешна при сумме не ниже сложности; успех не создаёт неуказанных ресурсов.",
    "door": (
        "Успех проверки отпирает замок, но не открывает дверь "
        "автоматически; провал сохраняет замок запертым."
    ),
    "trap": "Успех позволяет избежать указанного урона ловушки; провал наносит только этот урон.",
    "advantage": (
        "Преимущество: взять больший из двух d20, затем прибавить "
        "модификатор; сравнить со сложностью."
    ),
    "disadvantage": (
        "Помеха: взять меньший из двух d20, затем прибавить модификатор; сравнить со сложностью."
    ),
    "damage": (
        "Иммунитет обнуляет урон. Иначе сопротивление применяется один "
        "раз: половина вниз. Иначе уязвимость удваивает урон. HP не "
        "ниже нуля."
    ),
    "heal": "Лечение восстанавливает здоровье живой цели не выше её максимума.",
    "movement": (
        "Каждый фут пути стоит terrain_cost футов движения. Весь "
        "объявленный переход совершается только при достаточном "
        "остатке. Вопрос о возможности не расходует движение."
    ),
    "spell_slot": (
        "Известное заклинание требует одной доступной ячейки не ниже "
        "своего уровня; при недоступности ячейка не тратится. Вопрос о "
        "возможности не создаёт эффект."
    ),
    "cantrip": (
        "Известный заговор в данном сценарии не требует ячейки; "
        "остальные препятствия отсутствуют. Вопрос о возможности не "
        "означает применение."
    ),
    "concentration": (
        "Сложность спасброска max(10, половина урона вниз). Провал "
        "прекращает текущую концентрацию; фактически начатая новая "
        "концентрация заменяет прежнюю."
    ),
    "death_save": (
        "При 0 HP: 1 даёт два провала, 2–9 один провал, 10–19 один "
        "успех, 20 восстанавливает 1 HP. Три провала или больше "
        "означают смерть; три успеха стабилизируют без сознания и "
        "обнуляют счётчики."
    ),
    "nonlethal": (
        "Домашнее правило владельца: объявленное нелетальное попадание "
        "в ближнем бою оставляет цель без сознания при 0 HP и сразу "
        "стабильной; это не состояние Stunned."
    ),
    "ranged": (
        "До normal футов дальность обычная; дальше до maximum "
        "включительно атака с помехой; за maximum она недоступна."
    ),
    "bonus_action": (
        "В этом ходу разрешено одно бонусное действие без исключений. "
        "Вопрос о возможности его не тратит."
    ),
    "reaction": "Разрешена одна реакция до её восстановления. Вопрос о возможности её не тратит.",
    "inventory": (
        "Передача возможна только от текущего держателя. Хранение не "
        "меняет законное право собственности. Вопрос о передаче не "
        "перемещает предмет."
    ),
    "charges": (
        "Каждое фактически выполненное применение тратит один заряд; без заряда эффекта нет."
    ),
    "rest": (
        "В этом сценарии подтверждённый длительный отдых живого героя "
        "полностью восстанавливает HP и ячейки и снимает один уровень "
        "истощения."
    ),
    "duration": (
        "Отсчёт указан в минутах; по истечении остатка эффект "
        "заканчивается без автоматического продления."
    ),
    "quest": (
        "Условие выполнено только после фактического возврата и "
        "принятия предмета. Подтверждение выполнения само по себе не "
        "выдаёт награду."
    ),
    "reward": (
        "Фактическая выплата возможна после выполнения условия и при "
        "достаточных средствах плательщика. Обещание или вопрос о "
        "выплате денег не передаёт."
    ),
    "unknown": (
        "Достоверны только перечисленные known_facts. Вопрос игрока не "
        "доказывает подразумеваемого события."
    ),
    "craft": (
        "Материалы, инструмент и поддерживаемый способ обязательны. При "
        "попытке расходуется needed материалов и stamina_cost ST. Успех "
        "при сумме не ниже сложности; недобор до трёх допускает лишь "
        "объявленный частичный результат. Провал не возвращает расход."
    ),
    "repair": (
        "Ремонт использует те же явно объявленные проверки и расходы, "
        "что и работа с материалом. Частичный результат остаётся "
        "незавершённым; неизвестные свойства не добавляются."
    ),
    "ability": (
        "Физическую попытку можно предпринять, но достижимость цели "
        "требует зарегистрированного required_capability. При "
        "отсутствии свойства бросок D20 не создаёт его; расходов и "
        "урона в этой проверке нет."
    ),
}
FRAME_KINDS = [
    ["attack"],
    ["save"],
    ["advantage", "disadvantage"],
    ["damage"],
    ["movement"],
    ["heal"],
    ["spell_slot", "cantrip", "overcast"],
    ["concentration"],
    ["death_save", "nonlethal", "damage_zero", "stabilize"],
    ["ranged"],
    ["bonus_action", "reaction"],
    ["charges", "rest", "duration"],
    ["skill", "door", "trap", "social"],
    ["craft", "repair"],
    ["ability"],
    ["catalog_lookup"],
    ["inventory"],
    ["unknown"],
    ["quest"],
    ["reward"],
]
MODES = ["A"] * 5 + ["B"] * 10 + ["C"] * 4 + ["D"]


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


def state(r, npc):
    maximum = r.randint(68, 98)
    return dict(
        hp=r.randint(38, maximum),
        hp_max=maximum,
        mp=r.randint(0, 7),
        npc_agreed=False,
        conscious=True,
        dead=False,
        stable=False,
        failures=0,
        successes=0,
        speed=r.choice([35, 45, 55, 65]),
        movement_spent=r.randint(1, 24),
        place="исходная позиция",
        slots=r.randint(0, 4),
        slots_max=4,
        slot_level=r.randint(1, 6),
        concentration="защитное заклинание",
        locked=True,
        door_open=False,
        bonus_left=r.randrange(2),
        reaction_left=r.randrange(2),
        holder="герой",
        owner="герой",
        charges=r.randrange(8),
        exhaustion=r.randrange(4),
        duration=r.randint(1, 20),
        effect_active=True,
        condition_met=False,
        coins=r.randint(31, 72),
        npc_coins=r.randint(15, 85),
        materials=r.randint(1, 12),
        stamina=r.randint(8, 15),
        quality="повреждённый предмет",
        capabilities=r.choice([[], ["flight"], ["water_breathing"]]),
        known_facts=["Награда обещана за фактический возврат предмета и его принятие."],
    )


def parameters(kind, r, b, item, npc):
    p = dict(
        roll=r.randint(2, 19),
        modifier=r.randint(5, 12),
        threshold=r.randint(13, 28),
        damage=r.randint(5, 18),
    )
    if kind == "overcast":
        p.update(
            mp_cost=r.randint(1, 10),
            known=r.choice([True, True, False]),
            consent=r.choice([True, False]),
            payment=r.choice(["hp", "exhaustion"]),
        )
        b["hp"] = r.randint(1, 8)
    if kind == "social":
        p.update(
            constraints_known=r.choice([True, True, False]),
            authority_known=r.choice([True, True, False]),
            authority=r.choice([True, True, False]),
            feasible=r.choice([True, True, False]),
            vital_violated=r.choice([True, False, False]),
        )
    if kind == "attack":
        p["modifier"] = r.randint(10, 17)
        p["threshold"] = max(18, p["roll"] + p["modifier"] + r.choice([-3, -1, 0, 0, 1, 3]))
    if kind in ("advantage", "disadvantage"):
        p["dice"] = [r.randint(2, 19), r.randint(2, 19)]
    if kind == "damage":
        mode = r.randrange(4)
        p.update(raw=r.randint(31, 65), immune=mode == 0, resistant=mode == 1, vulnerable=mode == 2)
        b["hp"] = b["hp_max"]  # This reference family never involves massive-damage death.
    if kind == "heal":
        p["healing"] = r.randint(5, 25)
    if kind == "movement":
        p.update(
            distance=r.randint(7, 28),
            terrain_cost=r.choice([1, 2]),
            destination="край участка",
            intent_only=r.choice([True, False]),
        )
    if kind in ("spell_slot", "cantrip"):
        p.update(
            known=r.choice([True, True, False]),
            spell_level=r.randint(1, 5),
            intent_only=r.choice([True, False]),
        )
    if kind == "concentration":
        p.update(
            damage=r.choice([n for n in range(7, 60) if n != 22]),
            save_total=r.randint(8, 25),
            new_spell_cast=r.choice([True, False]),
            new_spell="сигнальное заклинание",
        )
    if kind == "death_save":
        b.update(hp=0, conscious=False, failures=r.randrange(3), successes=r.randrange(3))
        p["roll"] = r.choice([1, 2, 4, 6, 8, 10, 12, 16, 19, 20])
    if kind in ("damage_zero", "stabilize"):
        b.update(
            hp=0, conscious=False, stable=False, failures=r.randrange(3), successes=r.randrange(3)
        )
        if kind == "damage_zero":
            p.update(
                raw=r.choice([r.randint(1, 15), b["hp_max"]]), critical=r.choice([True, False])
            )
        else:
            p["threshold"] = 10
    if kind == "nonlethal":
        p["damage"] = b["hp"] + r.randint(0, 5)
    if kind == "ranged":
        p.update(normal=r.choice([40, 70, 100]), maximum=180, distance=r.choice([35, 85, 150, 195]))
    if kind in ("bonus_action", "reaction"):
        p["intent_only"] = r.choice([True, False])
    if kind == "inventory":
        p.update(actor="герой", recipient=npc, item_name=item, intent_only=False)
    if kind == "charges":
        p["uses"] = r.randint(1, 6)
    if kind == "duration":
        p["elapsed"] = r.randint(1, 25)
    if kind == "quest":
        p["returned_and_accepted"] = b["holder"] == npc
    if kind == "reward":
        p.update(amount=r.randint(12, 43), intent_only=r.choice([True, False]))
    if kind == "unknown":
        p["question_fact"] = r.choice(
            ["Обещанная награда уже фактически передана герою.", *b["known_facts"]]
        )
    if kind in ("craft", "repair"):
        plan, materials, tools = r.choice(PLANS)
        p.update(
            plan=plan,
            material_description=materials,
            tool_description=tools,
            needed=r.randint(2, 8),
            tools_available=r.choice([True, True, False]),
            supported=True,
            stamina_cost=2,
            partial_allowed=True,
        )
    if kind == "ability":
        p["required_capability"] = r.choice(
            ["flight", "create_currency", "heal_dead", "water_breathing"]
        )
    return p


def generate(source, output, *, groups_per_split=None, excluded_entities=()):
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    groups_per_split = groups_per_split or {"train": 1344, "val": 168, "test": 168}
    catalog = {
        r["entity_id"]: r
        for r in (
            json.loads(line)
            for line in (source / "entity_index.jsonl").read_text(encoding="utf-8").splitlines()
        )
    }
    groups = {s: [] for s in groups_per_split}
    for fold in groups:
        seen = set()
        if fold == "ood":
            groups[fold] = sorted(
                set(catalog) - set(excluded_entities), key=lambda x: digest([SEED, "ood", x])
            )[: groups_per_split[fold]]
            continue
        if (source / "source_groups.json").is_file():
            groups[fold] = json.loads((source / "source_groups.json").read_text())[fold]
        else:
            for line in (source / (fold + ".jsonl")).read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                entity = row["source"]["entity_id"]
                if entity not in seen:
                    groups[fold].append(entity)
                    seen.add(entity)
        groups[fold] = sorted(groups[fold], key=lambda x: digest([SEED, x]))[
            : groups_per_split[fold]
        ]
    if any(len(v) != groups_per_split[k] for k, v in groups.items()):
        raise ValueError("Insufficient source groups")
    if len(set(e for v in groups.values() for e in v)) != sum(map(len, groups.values())):
        raise ValueError("Entity split overlap")
    counts = {}
    all_ids = []
    split_map = {}
    for fold, entities in groups.items():
        with (output / (fold + ".jsonl")).open("x", encoding="utf-8") as dest:
            count = 0
            for index, entity in enumerate(entities):
                rng = random.Random(int(digest([SEED, entity])[:16], 16))
                names = rng.sample(NAMES[fold], 2)
                place, detail, concern = rng.choice(PLACES[fold])
                temperament, preference, manner = rng.choice(TEMPERAMENTS)
                scene = dict(
                    place=place,
                    detail=detail,
                    concern=concern,
                    npc=names[0],
                    other_npc=names[1],
                    temperament=temperament,
                    preference=preference,
                    manner=manner,
                )
                item = rng.choice(ITEMS)
                scene["item"] = item
                scene["first_person_preference"] = {
                    "осторожный": "предпочитаю сначала проверить условия",
                    "прямой": "ценю ясные договорённости",
                    "педантичный": "слежу за порядком действий",
                    "сочувствующий": "думаю о последствиях для людей",
                    "недоверчивый": "опасаюсь преждевременных выводов",
                    "практичный": "берегу время и материалы",
                }[temperament]
                chain = state(rng, names[0])
                if index % 3 == 0:
                    chain["holder"] = "спутник"
                history = []
                trace = []
                group = "v5:" + entity
                split_map[group] = fold
                for frame, options in enumerate(FRAME_KINDS):
                    if fold == "ood" and frame < 16:
                        continue
                    recipe = index % 8
                    chains = [
                        ["inventory", "unknown", "quest", "reward"],
                        ["door", "trap", "charges", "duration"],
                        ["damage", "heal", "damage", "heal"],
                        ["inventory", "inventory", "inventory", "inventory"],
                        ["movement", "movement", "skill", "door"],
                        ["craft", "repair", "duration", "ability"],
                        ["bonus_action", "reaction", "bonus_action", "reaction"],
                        ["charges", "duration", "charges", "duration"],
                    ]
                    if fold == "ood":
                        chains = [
                            ["inventory", "charges", "inventory", "duration"],
                            ["door", "charges", "duration", "heal"],
                            ["damage", "heal", "rest", "damage"],
                            ["craft", "inventory", "repair", "charges"],
                            ["ability", "movement", "reaction", "bonus_action"],
                            ["quest", "unknown", "inventory", "reward"],
                            ["reaction", "rest", "reaction", "charges"],
                            ["duration", "charges", "heal", "duration"],
                        ]
                    kind = chains[recipe][frame - 16] if frame >= 16 else rng.choice(options)
                    before = deepcopy(chain if frame >= 16 else state(rng, names[0]))
                    p = parameters(kind, rng, before, item, names[0])
                    if frame >= 16:
                        scene["chain_family"] = recipe
                        if recipe == 2 and kind == "damage":
                            # parameters() does not get to reset the chain's HP.
                            before = deepcopy(chain)
                            p.update(
                                raw=rng.randint(7, 14),
                                immune=False,
                                resistant=False,
                                vulnerable=False,
                            )
                        if recipe == 3 and kind == "inventory":
                            p.update(
                                actor=before["holder"],
                                recipient=names[0] if frame % 2 == 0 else "герой",
                            )
                        if recipe == 4 and kind == "movement":
                            p.update(
                                distance=4,
                                terrain_cost=2,
                                intent_only=frame == 16,
                                destination="край участка",
                            )
                        if recipe == 5 and kind in ("craft", "repair"):
                            p.update(needed=2, tools_available=True)
                    if kind == "catalog_lookup":
                        p.update(
                            name=catalog[entity]["entity_name"],
                            category=catalog[entity]["entity_category"],
                        )
                    result = resolve(kind, p, before)
                    mode = MODES[frame]
                    answer, style = render(kind, p, before, result, scene, mode, rng, fold)
                    rule_mode = (
                        "apply_rules"
                        if frame < 5 or index % 4 == 0 and frame < 16
                        else "narrate_engine_result"
                    )
                    payload = {
                        "scene": scene,
                        "player_request": request(kind, p, before, scene, rng),
                        "rules": RULES[kind],
                        "operation": kind,
                        "parameters": p,
                        "state_before": before,
                        "action_phase": "intent_only"
                        if p.get("intent_only")
                        else "performed_action",
                        "response_mode": mode,
                    }
                    if rule_mode == "narrate_engine_result":
                        payload["engine_result"] = result
                    if frame == 15:
                        payload["catalog_lookup"] = {
                            "mode": "provided_index_not_direct_sql",
                            "record": catalog[entity],
                            "unknown": (
                                "Других свойств и характеристик исходная карточка в этом пакете "
                                "не предоставляет."
                            ),
                        }
                    fields = {
                        "overcast": ["mp", "hp", "exhaustion", "conscious", "dead"],
                        "social": ["npc_agreed"],
                        "attack": ["hp"],
                        "save": [],
                        "skill": [],
                        "door": ["locked", "door_open"],
                        "trap": ["hp"],
                        "advantage": [],
                        "disadvantage": [],
                        "damage": ["hp", "hp_max", "conscious"],
                        "heal": ["hp", "hp_max"],
                        "movement": ["speed", "movement_spent", "place"],
                        "spell_slot": ["slots", "slot_level"],
                        "cantrip": ["slots"],
                        "concentration": ["concentration"],
                        "death_save": [
                            "hp",
                            "failures",
                            "successes",
                            "stable",
                            "dead",
                            "conscious",
                        ],
                        "nonlethal": ["hp", "stable", "conscious"],
                        "damage_zero": ["hp", "hp_max", "stable", "failures", "dead", "conscious"],
                        "stabilize": ["hp", "stable", "failures", "successes", "conscious"],
                        "ranged": [],
                        "bonus_action": ["bonus_left"],
                        "reaction": ["reaction_left"],
                        "inventory": ["holder", "owner"],
                        "charges": ["charges"],
                        "rest": ["hp", "hp_max", "slots", "slots_max", "exhaustion"],
                        "duration": ["duration", "effect_active"],
                        "quest": ["condition_met", "holder", "coins"],
                        "reward": ["condition_met", "coins", "npc_coins"],
                        "unknown": ["known_facts", "holder", "condition_met", "coins"],
                        "craft": ["materials", "stamina", "quality"],
                        "repair": ["materials", "stamina", "quality"],
                        "ability": ["capabilities"],
                        "catalog_lookup": [],
                    }[kind]
                    payload["state_before"] = {k: before[k] for k in fields}
                    if "engine_result" in payload:
                        receipt = {
                            k: deepcopy(result[k])
                            for k in ("operation", "numbers", "success", "committed")
                        }
                        receipt["state_after"] = {k: result["state_after"][k] for k in fields}
                        if result["predicted_state_if_executed"] is not None:
                            receipt["predicted_state_if_executed"] = {
                                k: result["predicted_state_if_executed"][k] for k in fields
                            }
                        payload["engine_result"] = receipt
                    if frame > 16:
                        payload["scene"] = {k: scene[k] for k in ("place", "npc", "other_npc")}
                    current = [
                        {"role": "user", "content": dump(payload)},
                        {"role": "assistant", "content": answer},
                    ]
                    messages = (
                        [{"role": "system", "content": SYSTEM}]
                        + (history if frame >= 16 else [])
                        + current
                    )
                    uid = f"v5_{fold}_{index:04}_{frame:02}"
                    all_ids.append(uid)
                    row = {
                        "id": uid,
                        "group_id": group,
                        "split": fold,
                        "version": "5.0.0",
                        "task": kind,
                        "mode": rule_mode,
                        "synthetic": True,
                        "human_reviewed": False,
                        "messages": messages,
                        "state_before": before,
                        "parameters": p,
                        "engine_result": result,
                        "state_after": result["state_after"],
                        "style": style,
                        "scene": scene,
                        "chain_family": recipe if frame >= 16 else None,
                        "trajectory": deepcopy(trace) if frame >= 16 else [],
                        "source": {
                            "mode": "provided_v41_index_lineage",
                            "entity_id": entity,
                            "entity_digest": catalog[entity]["entity_digest"],
                            "sqlite_access_claimed": False,
                            "producer": "faun_v5_declared_scenario_reference",
                        },
                        "training_target": "last_assistant_only",
                    }
                    dest.write(dump(row) + "\n")
                    count += 1
                    if frame >= 16:
                        history += current
                        chain = deepcopy(result["state_after"])
                        trace.append(
                            {
                                "operation": kind,
                                "parameters": p,
                                "state_before": before,
                                "engine_result": result,
                            }
                        )
            counts[fold] = count
    (output / "entity_index.jsonl").write_bytes((source / "entity_index.jsonl").read_bytes())
    (output / "group_splits.json").write_text(dump(split_map) + "\n", encoding="utf-8")
    manifest = {
        "version": "5.0.0",
        "status": "GENERATED_VALIDATION_PENDING",
        "splits": counts,
        "groups": len(split_map),
        "source_index_records": len(catalog),
        "used_source_entities": sum(map(len, groups.values())),
        "source_sqlite_available": False,
        "seed": SEED,
        "training_steps": 0,
        "human_reviewed": 0,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(generate(a.source, a.output)))


if __name__ == "__main__":
    main()
