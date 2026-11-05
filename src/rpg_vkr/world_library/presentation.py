"""One human-readable catalog view shared by the master and review exports."""

import re

from rpg_vkr.world_library.model import digest, normalized

PROFILE_NAMES = {
    "weapon": "Оружие",
    "armour": "Броня",
    "ammunition": "Боеприпасы",
    "tool": "Инструменты",
    "medicine": "Медицина",
    "poison": "Вымышленные яды",
    "food": "Еда",
    "ingredient": "Ингредиенты",
    "plant": "Растения",
    "ore": "Руды",
    "material": "Материалы",
    "recipe": "Рецепты",
    "book": "Книги",
    "quest": "Квестовые вещи",
    "npc": "NPC",
    "creature": "Существа",
    "boss": "Боссы",
    "spell": "Магические формулы",
    "rune": "Руны",
    "scroll": "Свитки",
    "combination": "Комбинации магии",
    "skill": "Навыки",
    "race": "Расы",
    "source_creature": "Существа из источников",
    "source_equipment": "Снаряжение из источников",
    "source_reference": "Справочные разделы",
}
LABELS = {
    "mass_g": "Масса г",
    "durability": "Прочность",
    "quality": "Качество",
    "penetration": "Пробитие",
    "defence": "Защита",
    "hands": "Руки",
    "level": "Уровень",
    "hp_max": "Максимум HP",
    "armour_class": "КД",
    "damage_dice": "Урон",
    "age_years": "Возраст лет",
    "profession": "Занятие",
    "social_status": "Положение",
    "beliefs": "Убеждения",
    "motivation": "Мотив",
    "territory": "Местность",
    "diet": "Питание",
    "tactics": "Поведение",
    "initial_mood": "Начальное настроение",
    "season": "Сезон",
    "habitat": "Место произрастания",
    "harvest": "Сбор",
    "school": "Школа",
    "nature": "Природа",
    "mp": "Стоимость MP",
    "duration_turns": "Длительность ходов",
    "minutes": "Время минут",
    "difficulty": "Сложность",
    "mode": "Операция",
    "potency": "Сила действия",
    "nutrition": "Питательность",
    "shelf_days": "Срок хранения дней",
    "effect": "Действие",
    "subject": "Тема",
    "objective": "Задача",
    "issuer": "Отправитель",
    "author": "Автор",
    "lifespan": "Продолжительность жизни лет",
    "trait": "Особенность",
    "size": "Размер",
}
NON_NARRATIVE = (
    "Справочная запись",
    "Числовые параметры",
    "Текст биографии",
    "Это оригинальное краткое",
    "Описание не разрешает",
    "Материалы списываются",
    "Начальное отношение",
    "Личные цели могут измениться",
    "Более высокая ступень",
    "Это авторская формула",
    "Региональный вариант не даёт",
    "Это игровое растение",
    "Эти визуальные черты",
    "Обработчик",
    "Движок должен",
)


def prose(value):
    """Remove known generator commentary, retaining the stored narrative statements."""
    if not isinstance(value, str):
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", value.strip())
    return " ".join(s for s in sentences if not s.startswith(NON_NARRATIVE)).strip()


def display_name(record):
    return record["attributes"].get("source_name") or record["name"]


def card(record, *, resolve=None, revision=None):
    a, profile = record["attributes"], record["profile"]
    name = display_name(record)
    appearance = a.get("appearance", a.get("appearance_homebrew", ""))
    appearance = re.sub(r"^Авторская внешность.*?\)\.\s*", "", appearance)
    appearance = prose(appearance)
    description = prose(a.get("biography") or record["description"])
    facts = []
    if profile == "source_creature":
        from rpg_vkr.world_library.creature_rules import compile_creature

        rules = compile_creature(record)
        description = f"{name}. {a['source_size']} {a['source_type'].casefold()}."
        facts.extend(
            [
                ("HP", str(rules["hp_max"])),
                ("КД", str(rules["armour_class"])),
                ("Опасность", a["challenge_rating"] or "Оценка отсутствует"),
                ("Скорость", a["speed"] or "Авторская базовая скорость"),
                (
                    "Характеристики",
                    "; ".join(
                        label + " " + str(rules[key])
                        for key, label in (
                            ("strength", "СИЛ"),
                            ("dexterity", "ЛОВ"),
                            ("constitution", "ТЕЛ"),
                            ("intelligence", "ИНТ"),
                            ("wisdom", "МУД"),
                            ("charisma", "ХАР"),
                        )
                    ),
                ),
            ]
        )
        for attack in a.get("actions_v2", {}).get("actions", []):
            facts.append(("Атака", f"{attack['name']}: {attack['bonus']:+d}, {attack['dice']}"))
        mechanics = {
            "version": rules["library_rules_version"],
            "pending_features": rules["unsupported_source_features"],
            "homebrew_fields": rules["homebrew_fields"],
        }
    else:
        mechanics = {
            "version": "descriptive"
            if profile in {"skill", "race", "source_reference"}
            else "engine-template",
            "pending_features": [],
            "homebrew_fields": [],
        }
        for key, label in LABELS.items():
            if key in a:
                value = a[key]
                value = {
                    "wary": "настороженное",
                    "calm": "спокойное",
                    "angry": "сердитое",
                    "craft": "создание",
                    "disassemble": "разборка",
                    "salvage": "разборка",
                }.get(str(value), str(value))
                facts.append((label, value))
        if "abilities" in a:
            facts.insert(
                0,
                (
                    "Характеристики",
                    ", ".join(
                        f"{label} {a['abilities'][key]}"
                        for key, label in (
                            ("strength", "СИЛ"),
                            ("dexterity", "ЛОВ"),
                            ("constitution", "ТЕЛ"),
                            ("intelligence", "ИНТ"),
                            ("wisdom", "МУД"),
                            ("charisma", "ХАР"),
                        )
                    ),
                ),
            )
        if "damage_count" in a:
            facts.append(("Урон", f"{a['damage_count']}d{a['damage_die']}"))
        if profile == "source_equipment":
            from rpg_vkr.world_library.equipment_rules import compile_equipment, pending_features

            rules = compile_equipment(record)
            if "pack_v1" in a:
                pack = a["pack_v1"]
                facts.insert(
                    0,
                    (
                        "Упаковка",
                        f"{pack['quantity']} шт.; {pack['pack_price_cp']} медных за всю партию",
                    ),
                )
            description = prose(a.get("purpose_homebrew") or f"{name}. Раздел {a['section']}.")
            translations = {
                "damage": "Урон",
                "properties": "Свойства",
                "weight": "Вес",
                "price": "Цена источника",
                "cost": "Цена источника",
                "ac": "КД",
                "type": "Тип",
                "armor_class": "КД",
            }
            facts.extend(
                (translations.get(r["field"], r["field"]), r["value"])
                for r in a["facts"]
                if r["value"]
            )
            mechanics.update(
                version=rules["rules_version"],
                homebrew_fields=rules["homebrew_fields"],
                pending_features=pending_features(record, rules),
            )
    if record["price_cp"] or profile in {
        "weapon",
        "armour",
        "ammunition",
        "tool",
        "food",
        "medicine",
        "poison",
        "material",
        "ore",
        "ingredient",
        "plant",
        "source_equipment",
    }:
        facts.append(("Цена медных", str(record["price_cp"])))
    if profile == "source_reference":
        labels = {
            "level": "Уровень",
            "school": "Школа",
            "casting_amount": "Время применения",
            "casting_unit": "Единица времени",
            "range_feet": "Дистанция футов",
            "range_kind": "Вид дистанции",
            "duration_seconds": "Длительность секунд",
            "duration_kind": "Вид длительности",
            "components": "Компоненты",
            "concentration": "Концентрация",
            "ritual": "Ритуал",
            "class_names": "Классы",
            "hit_die_sides": "Кость здоровья",
            "minimum_level": "Требуемый уровень",
            "creature_type": "Вид",
            "sizes": "Размеры",
            "languages": "Языки",
            "darkvision_ft": "Тёмное зрение футов",
            "speed_walk_ft": "Ходьба футов",
            "speed_fly_ft": "Полёт футов",
            "speed_swim_ft": "Плавание футов",
            "speed_climb_ft": "Лазание футов",
            "rarity": "Редкость",
            "requires_attunement": "Нужна настройка",
            "charges_max": "Заряды",
            "item_type": "Тип предмета",
            "source_price": "Цена источника",
        }
        for key, value in a.get("details", {}).items():
            if key in labels and value not in ("", [], -1):
                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value)
                if type(value) is bool:
                    value = "да" if value else "нет"
                facts.append((labels[key], str(value)))
    parts, stock, related = [], [], []
    for link in record["links"]:
        target = resolve(link["target"]) if resolve else None
        target_name = display_name(target) if target else link["target"]
        row = {
            "id": link["target"],
            "name": target_name,
            "quantity": link["quantity"],
            "role": link["role"],
            "relation": link["relation"],
        }
        if link["relation"] == "component":
            parts.append(row)
        elif link["relation"] == "starting_inventory":
            stock.append(row)
        else:
            related.append(row)
        if link["relation"] == "species":
            facts.insert(0, ("Вид", target_name))
    if not appearance and parts:
        appearance = "; ".join(f"{p['role']}: {p['name']}" for p in parts) + "."
    return {
        "id": record["id"],
        "revision": revision,
        "digest": digest(record),
        "name": name,
        "profile": profile,
        "kind": PROFILE_NAMES[profile],
        "description": description,
        "appearance": appearance,
        "facts": facts,
        "composition": parts,
        "starting_inventory": stock,
        "related": related,
        "mechanics": mechanics,
        "provenance": record["provenance"],
        "template_only": True,
    }


def render(value):
    lines = [value["name"], value["kind"], value["description"]]
    if value["appearance"]:
        lines += ["Внешность", value["appearance"]]
    lines += [name + ": " + str(data) for name, data in value["facts"]]
    if value["composition"]:
        lines += ["Состав"] + [
            f"{r['role']}: {r['name']} × {r['quantity']}" for r in value["composition"]
        ]
    if value["starting_inventory"]:
        lines += ["Начальное имущество владельца"] + [
            f"{r['name']} × {r['quantity']}" for r in value["starting_inventory"]
        ]
    if value["related"]:
        lines += ["Связанные записи"] + [
            f"{r['role']}: {r['name']} × {r['quantity']}" for r in value["related"]
        ]
    return "\n".join(line for line in lines if line)


def family(record):
    """Group identical source names and regional homebrew variants together."""
    a = record["attributes"]
    if a.get("source_name"):
        name = a["source_name"]
    elif record["profile"] == "npc":
        name = a["profession"]
    else:
        name = a.get("purpose") or record["name"].split(":")[0]
    return record["profile"] + ":" + normalized(name)
