"""Reviewed construction constraints for new campaigns; catalog-v1 remains untouched."""

from copy import deepcopy

from rpg_vkr.domain.catalog_authoring import DESIGNS, MATERIALS

FORMS = (
    (
        "Руда",
        "Пруток",
        "Полоса",
        "Лист",
        "Пружинная проволока",
        "Пластина",
        "Закалённая заготовка",
        "Рунный сплав",
    ),
    (
        "Ветви",
        "Доска",
        "Сухая рейка",
        "Брус",
        "Ламели",
        "Гнутый каркас",
        "Пропитанная заготовка",
        "Резонансная сердцевина",
    ),
    (
        "Свежий сбор",
        "Перебранный сбор",
        "Сухой сбор",
        "Порошок",
        "Настой",
        "Вытяжка",
        "Концентрат",
        "Стабилизированная эссенция",
    ),
    (
        "Волокно",
        "Нить",
        "Полотно",
        "Холст",
        "Многослойный пакет",
        "Плетёный шнур",
        "Пропитанное полотно",
        "Рунное полотно",
    ),
    (
        "Сырая шкура",
        "Очищенная шкура",
        "Дублёная кожа",
        "Ременная полоса",
        "Многослойная кожа",
        "Плетёный ремень",
        "Промасленная кожа",
        "Тиснёная кожа",
    ),
    (
        "Обломки",
        "Промытая крошка",
        "Сухой песок",
        "Шлифованный брусок",
        "Обсидиановая пластина",
        "Керамическая пластина",
        "Закалённая керамика",
        "Рунная пластина",
    ),
    (
        "Руда",
        "Слиток",
        "Проволока",
        "Лист",
        "Пруток",
        "Чеканная пластина",
        "Бронзовая заготовка",
        "Рунная бронза",
    ),
    (
        "Крупная соль",
        "Очищенная соль",
        "Сухие кристаллы",
        "Тонкий порошок",
        "Рассол",
        "Фильтрат",
        "Концентрированный реагент",
        "Стабилизированный реагент",
    ),
    (
        "Стеклобой",
        "Очищенная крошка",
        "Порошок",
        "Стеклянная трубка",
        "Линза",
        "Флакон",
        "Жаростойкая колба",
        "Оптическая призма",
    ),
    (
        "Необработанный кристалл",
        "Очищенный кристалл",
        "Крошка",
        "Огранённый кристалл",
        "Фокусирующая пластина",
        "Резонатор",
        "Заряженный резонатор",
        "Стабильная матрица",
    ),
)
METALS = (
    "Сталь",
    "Закалённая сталь",
    "Пружинная сталь",
    "Узорчатая сталь",
    "Посеребрённая сталь",
    "Бронза",
    "Обсидиан",
    "Рунная керамика",
    "Рунная сталь",
    "Звёздная сталь",
)
METAL_IDS = (
    "mat_0_0",
    "mat_0_1",
    "mat_0_2",
    "mat_0_3",
    "mat_0_4",
    "mat_6_6",
    "mat_5_4",
    "mat_5_7",
    "mat_0_6",
    "mat_0_7",
)
HOUSE_NAMES = (
    "Набор инструментов",
    "Переносной горн",
    "Алхимический комплект",
    "Складной верстак",
    "Походный фонарь",
    "Дорожный контейнер",
    "Лагерный навес",
    "Набор разведчика",
)


def build(published):
    data = deepcopy(published)
    data["revision"] = 2
    rows = {r["id"]: r for r in data["records"]}
    for row in rows.values():
        kind = row["kind"]
        if kind == "material":
            row["name"] = f"{MATERIALS[row['base']]}: {FORMS[row['base']][row['process']]}"
        elif kind in ("weapon", "armour"):
            _, family, m, p = row["id"].split("_")
            m, p = int(m), int(p)
            name = row["name"].split(" «")[0]
            material, title = METAL_IDS[m], METALS[m]
            if family in ("longbow", "focus"):
                material, title = f"mat_1_{m % 8}", "Древесный каркас " + str(m + 1)
            elif family == "light":
                material, title = (
                    f"mat_{4 if m < 5 else 3}_{m % 8}",
                    "Кожаная защита" if m < 5 else "Стёганая защита",
                )
            elif family == "shield" and m < 5:
                material, title = f"mat_1_{m}", "Окованный деревянный щит"
            row.update(
                material=material,
                construction="composite" if family in ("crossbow", "medium", "shield") else "solid",
            )
            row["name"] = f"{name} «{DESIGNS[p]}» — {title}, образец {m + 1}"
        elif kind == "household":
            _, m, p = row["id"].split("_")
            m, p = int(m), int(p)
            base = (0, 0, 8, 1, 8, (1, 3, 4, 0, 8)[m % 5], 3, 9)[p]
            row.update(material=f"mat_{base}_{m % 8}")
            row["name"] = f"{HOUSE_NAMES[p]} «{MATERIALS[base]}», исполнение {m + 1}"
        elif kind == "consumable":
            _, category, p, m = row["id"].split("_")
            p, m = int(p), int(m)
            base = {"potions": 2, "dressings": 3, "scrolls": 3, "ammunition": 0}[category]
            row["material"] = f"mat_{base}_{m % 8}"
            row["name"] = row["name"].split(":")[0] + f", состав {m + 1}"
            if category == "ammunition":
                row["name"] = f"Оперённый снаряд «{DESIGNS[p]}», наконечник {METALS[m]}"
                row["material"] = METAL_IDS[m]
        elif kind == "creature":
            _, family, role, habitat = row["id"].split("_")
            role, habitat = int(role), int(habitat)
            bodies = {
                "beast": (
                    "Травяной волк",
                    "Панцирный кабан",
                    "Пятнистая рысь",
                    "Иглоспин",
                    "Грозовой вепрь",
                    "Светлячный олень",
                    "Падальщик",
                    "Разъярённый медведь",
                ),
                "humanoid": (
                    "Следопыт-разбойник",
                    "Наёмный страж",
                    "Налётчик",
                    "Стрелок",
                    "Отступник-чародей",
                    "Полевой лекарь",
                    "Мародёр",
                    "Берсерк",
                ),
                "undead": (
                    "Голодный упырь",
                    "Костяной страж",
                    "Блуждающий мертвец",
                    "Костяной стрелок",
                    "Пепельный колдун",
                    "Хранитель склепа",
                    "Могильный собиратель",
                    "Неистовый мертвец",
                ),
                "arcane": (
                    "Ловчий конструкт",
                    "Каменный голем",
                    "Зеркальный охотник",
                    "Игольчатый конструкт",
                    "Грозовой элементаль",
                    "Живой источник",
                    "Пожиратель чар",
                    "Пламенный голем",
                ),
            }
            row["name"] = (
                bodies[family][role]
                + " — "
                + (
                    "лесной",
                    "степной",
                    "горный",
                    "болотный",
                    "руинный",
                    "пустынный",
                    "пещерный",
                    "прибрежный",
                    "тундровый",
                    "городской",
                )[habitat]
                + " ареал"
            )
            loot_base = {"beast": 4, "humanoid": (0, 3, 4)[role % 3], "undead": 3, "arcane": 9}[
                family
            ]
            row["loot"] = {f"mat_{loot_base}_0": 1 + role % 2}
            row["ecological_role"] = (
                "predator",
                "territorial",
                "predator",
                "ranged",
                "magic",
                "support",
                "scavenger",
                "territorial",
            )[role]
        elif kind == "event" and row["op"] == "production":
            row["resource"] = "mat_2_0"
        row["description"] = (
            row["name"]
            + ". "
            + {
                "weapon": "Основа несёт нагрузку; рукоять и крепления входят в состав изделия.",
                "armour": "Защита соответствует конструкции; реагенты не заменяют несущую основу.",
                "creature": (
                    "Поведение, запас сил и добыча определены движком; ареал ограничивает встречи."
                ),
            }.get(
                kind,
                "Доступность и расход определяются текущими правилами и подтверждёнными ресурсами.",
            )
        )
    for row in rows.values():
        if row["kind"] in ("weapon", "armour", "household", "consumable"):
            row["level"] = max(row["level"], rows[row["material"]]["level"])
    recipes = [r for r in rows.values() if r["kind"] == "recipe"]
    for recipe in recipes:
        _, direction, m, p = recipe["id"].split("_")
        m, p = int(m), int(p)
        recipe["outputs"] = []
        recipe["materials_by_output"] = {}
        if direction == "repair" and m in (2, 7):
            recipe["compatible_material"] = 1
        recipe["name"] = {
            "smithing": "Кузнечное дело",
            "alchemy": "Алхимия и перевязка",
            "production": "Мастерская",
            "repair": "Ремонт",
        }[direction] + f": {MATERIALS[m]}, ступень {p + 1}"
    for row in list(rows.values()):
        kind = row["kind"]
        if kind not in ("weapon", "armour", "household", "material", "consumable"):
            continue
        if kind == "material":
            m, p = row["base"], row["process"]
            if not p:
                continue
            direction = "production"
            ingredients = {f"mat_{m}_{p - 1}": 2}
        else:
            bits = row["id"].split("_")
            m, p = (
                (int(bits[-1]), int(bits[-2]))
                if kind == "consumable"
                else (int(bits[-2]), int(bits[-1]))
            )
            direction = (
                "alchemy"
                if kind == "consumable" and row["category"] in ("potions", "dressings")
                else "production"
            )
            if kind in ("weapon", "armour") and row["category"] not in (
                "longbow",
                "focus",
                "light",
            ):
                direction = "smithing"
            ingredients = {row["material"]: 2}
            if kind in ("weapon", "armour", "household"):
                extra = "mat_4_0" if row["material"] != "mat_4_0" else "mat_3_0"
                if kind == "household":
                    extra = "mat_1_0" if not row["material"].startswith("mat_1_") else "mat_0_0"
                ingredients[extra] = 1
                if row.get("construction") == "composite":
                    ingredients["mat_1_0"] = max(1, ingredients.get("mat_1_0", 0))
                if kind == "armour" and row["category"] in ("medium", "heavy", "shield"):
                    ingredients["mat_0_0"] = max(1, ingredients.get("mat_0_0", 0))
            if kind == "consumable" and row["category"] == "ammunition":
                ingredients["mat_1_0"] = 1
        recipe = rows[f"recipe_{direction}_{m}_{p}"]
        recipe["outputs"].append(row["id"])
        recipe["materials_by_output"][row["id"]] = ingredients
    for recipe in recipes:
        if recipe["outputs"]:
            recipe["ingredients"] = recipe["materials_by_output"][recipe["outputs"][0]]
            recipe["level"] = max(
                recipe["level"], min(rows[id]["level"] for id in recipe["outputs"])
            )
        recipe["description"] = (
            recipe["name"] + ". Выход выбирается отдельно; расход указан для конкретного изделия."
        )
    return data


def validate_construction(data):
    rows = {r["id"]: r for r in data["records"]}
    for row in rows.values():
        if row["kind"] in ("weapon", "armour"):
            base = rows[row["material"]]["base"]
            allowed = {"light": {3, 4}, "longbow": {1}, "focus": {1, 9}}.get(
                row["category"], {0, 1, 5, 6}
            )
            if base not in allowed:
                raise ValueError("Несовместимая несущая основа: " + row["id"])
        if row["kind"] != "recipe":
            continue
        if row["category"] == "repair":
            if row["outputs"]:
                raise ValueError("Ремонт не создаёт новый предмет.")
            continue
        if not row["outputs"] or set(row["outputs"]) != set(row["materials_by_output"]):
            raise ValueError("Рецепт не описывает все выходы.")
        for id, materials in row["materials_by_output"].items():
            if not materials or id in materials:
                raise ValueError("Самовоспроизводящийся или бесплатный рецепт.")
            if any(
                k not in rows or rows[k]["kind"] != "material" or type(n) is not int or n < 1
                for k, n in materials.items()
            ):
                raise ValueError("Неверный материальный вход.")
            product = rows[id]
            if product["kind"] != "material" and product["material"] not in materials:
                raise ValueError("В рецепте отсутствует основа изделия.")
            if any(rows[k]["level"] > product["level"] for k in materials):
                raise ValueError("Изделие требует недоступной на его уровне обработки.")
    return True
