"""Literal source features -> closed save/effect programs; unparsed clauses stay pending."""

import re

from rpg_vkr.domain.character import ability_modifier
from rpg_vkr.world_library.creature_actions import damage_components, text
from rpg_vkr.world_library.source_runtime import ABILITIES, CONDITIONS

ABILITY_WORDS = {
    "сил": "strength",
    "лов": "dexterity",
    "тел": "constitution",
    "инт": "intelligence",
    "муд": "wisdom",
    "хар": "charisma",
}
CONDITION_WORDS = {
    "ослеплен": "blinded",
    "ослеплён": "blinded",
    "очарован": "charmed",
    "глух": "deafened",
    "испуг": "frightened",
    "схвачен": "grappled",
    "недееспособ": "incapacitated",
    "невидим": "invisible",
    "парализ": "paralyzed",
    "окамен": "petrified",
    "отравлен": "poisoned",
    "сбит": "prone",
    "опутан": "restrained",
    "ошеломл": "stunned",
    "бессознан": "unconscious",
}


def action_matches(name, phrase):
    irregular = {
        "коготь": "когт",
        "когти": "когт",
        "когтем": "когт",
        "когтями": "когт",
        "щупальце": "щупальц",
        "щупальцем": "щупальц",
    }
    words = [irregular.get(w, w) for w in re.findall(r"[а-яё]+", phrase.casefold())]
    tokens = [
        irregular.get(w, w)
        for w in re.findall(r"[а-яё]+", name.casefold())
        if w not in {"атака", "атаки"}
    ]
    return bool(tokens) and all(
        any(w.startswith(t[: max(3, len(t) - 2)]) for w in words) for t in tokens
    )


def source_sequence(body, actions):
    if any(w in body for w in ("или", "если", "может", "заклин", "вместо")):
        return []
    counts = {
        "одну": 1,
        "одна": 1,
        "одним": 1,
        "две": 2,
        "два": 2,
        "двумя": 2,
        "три": 3,
        "тремя": 3,
        "четыре": 4,
        "пять": 5,
        "шесть": 6,
    }
    match = re.search(r"совершает\s+(\d+|" + "|".join(counts) + r")\s+атак[а-я]*", body)
    if not match:
        return []
    total = counts.get(match[1], int(match[1]) if match[1].isdigit() else 0)
    if not 1 <= total <= 8:
        return []
    tail = body[match.end() :].strip(" :.,")
    options = [
        i for i, a in enumerate(actions) if a["complete"] and action_matches(a["name"], tail)
    ]
    if len(options) == 1 and (
        len(actions) == 1 or not re.search(r"\b(?:" + "|".join(counts) + r")\b", tail)
    ):
        return [options[0]] * total
    result = []
    for part in re.split(r"[,;]|\s+и\s+", tail):
        count = re.search(r"\b(\d+|" + "|".join(counts) + r")\b", part)
        found = [
            i for i, a in enumerate(actions) if a["complete"] and action_matches(a["name"], part)
        ]
        if not count or len(found) != 1:
            return []
        n = counts.get(count[1], int(count[1]) if count[1].isdigit() else 0)
        if not 1 <= n <= 8:
            return []
        result.extend([found[0]] * n)
    return result if len(result) == total else []


def register(spec):
    def integer(lo, hi):
        return {"type": "integer", "minimum": lo, "maximum": hi}

    def obj(fields):
        return {
            "type": "object",
            "properties": fields,
            "required": list(fields),
            "additionalProperties": False,
        }

    def array(item, size):
        return {"type": "array", "items": item, "maxItems": size}

    def string(n):
        return {"type": "string", "maxLength": n}

    component = spec["creature_actions_v2"]["properties"]["actions"]["items"]["properties"][
        "components"
    ]["items"]
    effect = obj(
        {
            "ability": {"type": "string", "enum": list(ABILITIES)},
            "dc": integer(1, 40),
            "magical": {"type": "boolean"},
            "half": {"type": "boolean"},
            "components": array(component, 4),
            "condition": {"type": "string", "enum": ["", *CONDITIONS]},
            "rounds": integer(0, 14400),
            "repeat": {"type": "string", "enum": ["none", "start", "end"]},
        }
    )
    rule = obj(
        {
            "save_bonuses": obj({ability: integer(-10, 40) for ability in ABILITIES}),
            "magic_resistance": {"type": "boolean"},
            "pack_tactics": {"type": "boolean"},
            "legendary_resistance": integer(0, 10),
            "condition_immunities": array({"type": "string", "enum": list(CONDITIONS)}, 14),
            "legendary_max": integer(0, 10),
            "legendary": array(
                obj({"name": string(200), "cost": integer(1, 5), "index": integer(0, 29)}), 20
            ),
            "parry": integer(0, 10),
            "supported_names": array(string(200), 80),
            "multiattack": array(integer(0, 29), 8),
            "speed": integer(0, 1000),
            "fly_speed": integer(0, 1000),
            "riders": array(
                obj({"index": integer(0, 29), "base": array(component, 4), "effect": effect}), 30
            ),
            "ranges": array(
                obj(
                    {
                        "index": integer(0, 29),
                        "normal": integer(1, 2000),
                        "maximum": integer(1, 2000),
                    }
                ),
                30,
            ),
            "powers": array(
                obj(
                    {
                        "name": string(200),
                        "effect": effect,
                        "range": integer(1, 2000),
                        "shape": {
                            "type": "string",
                            "enum": ["one", "cone", "line", "sphere", "self"],
                        },
                        "size": integer(0, 1000),
                        "width": integer(1, 100),
                        "recharge": integer(0, 6),
                        "daily": integer(0, 10),
                    }
                ),
                20,
            ),
        }
    )
    spec["source_features_v3"] = rule
    spec["source_creature"]["properties"]["features_v3"] = rule


def validate(rules, actions=None):
    from rpg_vkr.world_library.model import schemas
    from rpg_vkr.world_library.model import validate as schema_validate

    schema_validate(rules, schemas()["source_features_v3"])
    for row in rules["riders"]:
        if not row["base"]:
            raise ValueError("Source rider requires base attack damage")
    for effect in [r["effect"] for r in rules["riders"]] + [r["effect"] for r in rules["powers"]]:
        if not effect["components"] and not effect["condition"]:
            raise ValueError("Empty saving-throw effect")
        if bool(effect["condition"]) != bool(effect["rounds"]):
            raise ValueError("Condition requires a finite duration")
    for r in rules["ranges"]:
        if r["normal"] > r["maximum"]:
            raise ValueError("Source range order")
    if actions is not None:
        if any(r["index"] >= len(actions["actions"]) for r in rules["ranges"] + rules["riders"]):
            raise ValueError("Missing source action reference")
        allowed = {i for i, a in enumerate(actions["actions"]) if a["complete"]}
        allowed.update(r["index"] for r in rules["riders"])
        if any(index not in allowed for index in rules["multiattack"]):
            raise ValueError("Partially implemented source multiattack")
        if any(
            r["index"] not in allowed or r["cost"] > rules["legendary_max"]
            for r in rules["legendary"]
        ):
            raise ValueError("Invalid legendary action")


def save_effect(body):
    lower = body.casefold()
    saves = list(re.finditer(r"спасброс(?:ок|ке|ка)\s+([а-яё]+)\s+сл\s*(\d+)", lower))
    if len(saves) != 1:
        return None
    ability = next(
        (name for stem, name in ABILITY_WORDS.items() if saves[0][1].startswith(stem)), None
    )
    if not ability or not 1 <= int(saves[0][2]) <= 40:
        return None
    # Clauses with choices, movement, secondary thresholds or immunities need their own program.
    forbidden = (
        "отброш",
        "отбрасыв",
        "отталк",
        "выберите",
        "на выбор",
        "один из",
        "максимум",
        "максимальное",
        "до тех пор",
        "если ",
        "пока ",
        "на 5 или",
        "на 10 или",
        "критическ",
        "иммунитет",
        "сопротивление",
        "бонусным действием",
        "действием может",
        "в начале каждого",
        "потерянные хиты",
        "поглощ",
        "проглот",
        "превращ",
        "проклят",
        "зараж",
        "болезн",
        "уменьша",
        "при условии",
        "не держит",
        "не может",
        "теряет",
        "восстанавливает",
        "каждый ход",
        "находящ",
        "дополнительн",
    )
    if any(word in lower for word in forbidden):
        return None
    matches = list(
        re.finditer(
            r"\b(\d+)\s*\(([1-9][0-9]?\s*[кd](?:4|6|8|10|12)(?:\s*[+-]\s*\d{1,2})?)\)", lower
        )
    )
    parts = []
    for index, match in enumerate(matches):
        # The source sometimes places the damage type before the average instead of after.
        end = matches[index + 1].start() if index + 1 < len(matches) else len(lower)
        start = matches[index - 1].end() if index else 0
        following = lower[match.end() : min(end, match.end() + 65)]
        preceding = lower[max(start, match.start() - 45) : match.start()]
        from rpg_vkr.world_library.creature_actions import ELEMENTS

        after = [(following.find(stem), v) for stem, v in ELEMENTS.items() if stem in following]
        before = [(preceding.rfind(stem), v) for stem, v in ELEMENTS.items() if stem in preceding]
        element = min(after)[1] if after else max(before)[1] if before else None
        if not element:
            return None
        parts.append({"dice": re.sub(r"\s", "", match[2]).replace("к", "d"), "element": element})
    conditions = {name for stem, name in CONDITION_WORDS.items() if stem in lower}
    if len(conditions) > 1 or len(parts) > 4:
        return None
    condition = next(iter(conditions), "")
    if condition and condition not in {"blinded", "poisoned", "paralyzed", "stunned"}:
        return None
    rounds = 0
    if condition:
        duration = re.search(r"(?:на|в течение)\s+(\d+)\s*(раунд|минут|час)", lower)
        if not duration:
            if "до конца своего следующего хода" in lower:
                rounds = 1
            else:
                return None
        else:
            rounds = int(duration[1]) * {"раунд": 1, "минут": 10, "час": 600}[duration[2]]
        if not 1 <= rounds <= 14400:
            return None
    # A bare save without a defined result is never a complete ability.
    if not parts and not condition:
        return None
    repeat = "none"
    if "повторять спасбросок" in lower or "повторить спасбросок" in lower:
        if "в конце" in lower:
            repeat = "end"
        elif "в начале" in lower:
            repeat = "start"
        else:
            return None
    return {
        "ability": ability,
        "dc": int(saves[0][2]),
        "magical": "магическ" in lower,
        "half": "половин" in lower,
        "components": parts,
        "condition": condition,
        "rounds": rounds,
        "repeat": repeat,
    }


def extract(stat, previous):
    raw_abilities = stat.get("характеристики", {})
    result = {
        "save_bonuses": {},
        "magic_resistance": False,
        "pack_tactics": False,
        "legendary_resistance": 0,
        "condition_immunities": [],
        "supported_names": [],
        "multiattack": [],
        "speed": 30,
        "fly_speed": 0,
        "riders": [],
        "ranges": [],
        "powers": [],
        "legendary_max": 0,
        "legendary": [],
        "parry": 0,
    }
    saves = stat.get("спасброски", {})
    for short, ability in ABILITY_WORDS.items():
        score = raw_abilities.get(short, 10) if isinstance(raw_abilities, dict) else 10
        if isinstance(score, dict):
            score = score.get("значение", 10)
        result["save_bonuses"][ability] = ability_modifier(score if type(score) is int else 10)
        if isinstance(saves, dict) and type(saves.get(short)) is int:
            result["save_bonuses"][ability] = saves[short]
    speed_match = re.search(r"^(\d+)", text(stat.get("скорость")))
    if speed_match:
        result["speed"] = min(1000, int(speed_match[1]))
    flying = re.search(r"(?:летая|полёт|полет)\s+(\d+)", text(stat.get("скорость")).casefold())
    if flying and int(flying[1]) <= 1000:
        result["fly_speed"] = int(flying[1])
    immune = stat.get("иммунитеты", {})
    if isinstance(immune, dict):
        for value in immune.get("состояния", []):
            if not isinstance(value, str):
                continue
            for stem, condition in CONDITION_WORDS.items():
                if stem in value.casefold():
                    result["condition_immunities"].append(condition)
            aliases = {
                "паралич": "paralyzed",
                "отравление": "poisoned",
                "очарование": "charmed",
                "ослепление": "blinded",
                "ошеломление": "stunned",
            }
            if value.casefold() in aliases:
                result["condition_immunities"].append(aliases[value.casefold()])
    result["condition_immunities"] = sorted(set(result["condition_immunities"]))
    for group in stat.values():
        if not isinstance(group, list):
            continue
        for row in group:
            if not isinstance(row, dict):
                continue
            name, body = text(row.get("название")), text(row.get("описание")).casefold()
            lower = name.casefold()
            if (
                lower == "тактика стаи"
                and "преимуществом" in body
                and "броски атаки" in body
                and "5 футов" in body
                and "дееспособный союзник" in body
                and not any(w in body for w in ("только", "оружием", "рукопаш", "дополн"))
            ):
                result["pack_tactics"] = True
                result["supported_names"].append(name[:200])
            if (
                "сопротивление" in lower
                and "маги" in lower
                and "преимущество" in body
                and "спасброс" in body
                and "заклинан" in body
                and not any(
                    w in body for w in ("если ", "кроме ", "только ", "пока ", "за исключением")
                )
            ):
                result["magic_resistance"] = True
                result["supported_names"].append(name[:200])
            legendary = re.fullmatch(r"легендарное сопротивление\s*\((\d+)/день\)", lower)
            if (
                legendary
                and int(legendary[1]) <= 10
                and "проваливает спасбросок" in body
                and "успеш" in body
            ):
                result["legendary_resistance"] = int(legendary[1])
                result["supported_names"].append(name[:200])
    indices = {}
    for i, row in enumerate(previous["actions"]):
        indices.setdefault(row["name"], []).append(i)
    multiattack = ""
    for raw in stat.get("действия", []):
        if not isinstance(raw, dict):
            continue
        name, body = text(raw.get("название"))[:200], text(raw.get("описание"))
        lower = body.casefold()
        if name.casefold().strip(".") == "мультиатака":
            multiattack = lower
        if name in indices:
            if len(indices[name]) != 1:
                continue
            index = indices[name][0]
            reach = re.search(r"досягаемость\s+(\d+)", lower)
            ranged = re.search(r"дистанция\s+(\d+)(?:\s*/\s*(\d+))?", lower)
            if reach or ranged:
                normal = int((ranged or reach)[1])
                maximum = int(ranged[2] or normal) if ranged else normal
                if 1 <= normal <= maximum <= 2000:
                    result["ranges"].append({"index": index, "normal": normal, "maximum": maximum})
            hit = re.search(r"попадание\s*:\s*", lower)
            separator = re.search(
                r"(?:[,.;]?\s*(?:и\s+)?цель\s+должна)", lower[hit.end() :] if hit else ""
            )
            if hit and separator:
                start = hit.end() + separator.start()
                base, complete = damage_components(lower[hit.end() : start].strip(" ,.;"))
                effect = save_effect(lower[start:])
                if complete and effect:
                    result["riders"].append({"index": index, "base": base, "effect": effect})
                    result["supported_names"].append(name)
            continue
        effect = save_effect(body)
        if not effect:
            continue
        recharge = re.search(r"перезарядка\s+([1-6])(?:[–—-]6)?", name.casefold())
        daily = re.search(r"(\d+)/день", name.casefold())
        if (
            "перезаряд" in name.casefold()
            and not recharge
            or "день" in name.casefold()
            and not daily
            or daily
            and int(daily[1]) > 10
            or any(w in lower for w in ("раз в день", "отдыха", "за сутки"))
        ):
            continue
        shape, size, width, maximum = "one", 0, 5, 0
        cone = re.search(r"(\d+)[ -]футов\w*\s+конус|конус\w*[^.]{0,35}?(\d+)\s+фут", lower)
        line = re.search(r"лини[яюе]\w*[^.]{0,30}?(\d+)\s+фут", lower)
        sphere = re.search(r"сфер\w*\s+радиусом\s+(\d+)", lower)
        if cone:
            shape, size = "cone", int(cone[1] or cone[2])
            maximum = size
        elif line:
            shape, size = "line", int(line[1])
            wide = re.search(r"шириной\s+(\d+)", lower)
            width = int(wide[1]) if wide else 5
            maximum = size
        elif sphere:
            shape, size = "sphere", int(sphere[1])
            distance = re.search(r"в пределах\s+(\d+)", lower)
            maximum = int(distance[1]) if distance else 0
        else:
            distance = re.search(r"в пределах\s+(\d+)", lower)
            if distance and not any(w in lower for w in ("каждое", "все существа")):
                maximum = int(distance[1])
        if not 1 <= maximum <= 2000 or not 0 <= size <= 1000 or not 1 <= width <= 100:
            continue
        # Components/durations alone don't cover lingering terrain, repeated damage or summons.
        if any(
            word in lower
            for word in (
                "создаёт",
                "создает",
                "остаётся",
                "остается",
                "призыва",
                "каждый раунд",
                "в начале хода",
                "непрозрачн",
            )
        ):
            continue
        result["powers"].append(
            {
                "name": name,
                "effect": effect,
                "shape": shape,
                "range": maximum,
                "size": size,
                "width": width,
                "recharge": int(recharge[1]) if recharge else 0,
                "daily": min(10, int(daily[1])) if daily else 0,
            }
        )
        result["supported_names"].append(name)
    result["powers"] = result["powers"][:20]
    from copy import deepcopy

    patched = deepcopy(previous["actions"])
    for rider in result["riders"]:
        patched[rider["index"]]["complete"] = True
    result["multiattack"] = source_sequence(multiattack, patched) or previous["multiattack"]
    if result["multiattack"]:
        result["supported_names"].append("Мультиатака")
    available = {i for i, a in enumerate(patched) if a["complete"]}
    header = text(stat.get("легендарные_действия_вступление")).casefold()
    limit = re.search(r"\b(\d+|одно|два|две|три|четыре|пять)\s+легендарн", header)
    if limit:
        word_counts = {"одно": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5}
        result["legendary_max"] = word_counts.get(
            limit[1], int(limit[1]) if limit[1].isdigit() else 0
        )
        if not 1 <= result["legendary_max"] <= 10:
            result["legendary_max"] = 0
        for row in stat.get("легендарные_действия", []):
            if not isinstance(row, dict):
                continue
            name, body = text(row.get("название"))[:200], text(row.get("описание")).casefold()
            if any(
                w in body
                for w in (
                    "если ",
                    "или ",
                    "перемещ",
                    "телепор",
                    "восстан",
                    "станов",
                    "после ",
                    "может ",
                    "использ",
                )
            ):
                continue
            attack = re.search(r"совершает одну атаку\s+([^.!]+)[.!]?$", body)
            if not attack:
                continue
            options = [i for i in available if action_matches(patched[i]["name"], attack[1])]
            cost = re.search(r"стоит\s+([1-5])", name.casefold())
            if len(options) == 1 and (int(cost[1]) if cost else 1) <= result["legendary_max"]:
                result["legendary"].append(
                    {"name": name, "cost": int(cost[1]) if cost else 1, "index": options[0]}
                )
                result["supported_names"].append(name)
    for row in stat.get("реакции", []):
        if not isinstance(row, dict) or text(row.get("название")).casefold() != "парирование":
            continue
        body = text(row.get("описание")).casefold()
        bonus = re.search(r"добавляет\s+([1-9])\s+к\s+кд", body)
        if (
            bonus
            and "рукопаш" in body
            and "видеть атакующего" in body
            and not any(w in body for w in ("если ", "дополнитель", "урона", "перемещ"))
        ):
            result["parry"] = int(bonus[1])
            result["supported_names"].append(text(row["название"]))
    result["supported_names"] = list(dict.fromkeys(result["supported_names"]))[:80]
    validate(result, previous)
    return result
