"""Deterministic authored design matrices; only supported effects enter the catalog."""

CLASSES = ("warrior", "archer", "rogue", "mage", "cleric", "artisan")
CLASS_NAMES = ("Воин", "Лучник", "Плут", "Маг", "Жрец", "Ремесленник")
MATERIALS = (
    "Железо",
    "Древесина",
    "Травы",
    "Ткань",
    "Кожа",
    "Камень",
    "Медь",
    "Соль",
    "Стекло",
    "Кристалл",
)
PROCESSES = (
    "Грубая основа",
    "Промывка",
    "Сушка",
    "Прессование",
    "Слоение",
    "Гибкое плетение",
    "Закаливание",
    "Резонанс",
)
WEAPONS = {
    "sword": ("Одноручный меч", "1d8", 1),
    "greatsword": ("Двуручный меч", "2d6", 2),
    "dagger": ("Кинжал", "1d4", 1),
    "axe": ("Топор", "1d12", 2),
    "hammer": ("Молот", "1d10", 2),
    "longbow": ("Лук", "1d8", 2),
    "crossbow": ("Арбалет", "1d10", 2),
    "focus": ("Магический посох", "1d6", 2),
}
DESIGNS = ("Дозор", "Точный выпад", "Натиск", "Оборона", "Истощение", "Разрыв", "Подсечка", "Охота")
MODES = {
    "direct": ("Прямое действие", 1, 0, 1, 0, 0),
    "focused": ("Точная форма", 1, 0, 1, 2, 0),
    "reach": ("Дальняя форма", 1, 1, 1, 3, 0),
    "pair": ("Парная форма", 2, 0, 1, 3, 0),
    "chain": ("Цепная форма", 3, 1, 1, 5, 0),
    "area": ("Общая форма", 4, 0, 1, 6, 0),
    "ritual": ("Ритуал", 1, 0, 30, -1, 0),
    "sacrifice": ("Кровная форма", 1, 0, 1, -1, 4),
    "delayed": ("Отложенная форма", 1, 0, 1, 1, 0),
    "sustained": ("Поддерживаемая форма", 1, 0, 1, 4, 0),
}
# A profile is a real combination of effects, never a change of color alone.
PROFILES = {
    "attack": [
        ("Огненный захват", "fire", "damage", "burn"),
        ("Ледяные путы", "cold", "damage", "slow"),
        ("Грозовой надлом", "lightning", "damage", "weaken"),
        ("Каменный толчок", "physical", "damage", "stagger"),
        ("Похищение жизни", "shadow", "damage", "leech"),
        ("Громовой разоружитель", "thunder", "damage", "disarm"),
        ("Терновая рана", "nature", "damage", "bleed"),
        ("Световая метка", "radiant", "damage", "mark"),
    ],
    "defense": [
        ("Щит поглощения", "physical", "shield", "anchor"),
        ("Стена ветра", "physical", "defence", "ranged_guard"),
        ("Огнестойкость", "fire", "resist", "defence"),
        ("Зимний покров", "cold", "resist", "anchor"),
        ("Заземление", "lightning", "resist", "restore_st"),
        ("Защита воли", "shadow", "resist", "clarity"),
        ("Упреждающий шаг", "physical", "defence", "haste"),
        ("Отражение удара", "physical", "reflect", "shield"),
    ],
    "healing": [
        ("Сшивание ран", "life", "heal", "anchor"),
        ("Очищение крови", "life", "heal", "cure_bleed"),
        ("Снятие ожогов", "life", "heal", "cure_burn"),
        ("Восстановление маны", "life", "restore_mp", "clarity"),
        ("Второе дыхание", "life", "restore_st", "haste"),
        ("Возвращение сознания", "life", "revive", "slow"),
        ("Живой источник", "life", "regenerate", "cure_poison"),
        ("Разрыв слабости", "life", "heal", "cure_weaken"),
    ],
    "research": [
        ("Путеводный свет", "knowledge", "light", "perception"),
        ("Открытый след", "knowledge", "reveal_items", "perception"),
        ("Поиск жизни", "knowledge", "reveal_actors", "clarity"),
        ("Чтение износа", "knowledge", "appraise", "craft"),
        ("Зов руды", "knowledge", "reveal_nodes", "craft"),
        ("Чтение троп", "knowledge", "reveal_routes", "haste"),
        ("Разрыв иллюзии", "knowledge", "dispel", "perception"),
        ("Чуткий дозор", "knowledge", "reveal_actors", "ranged_guard"),
    ],
    "support": [
        ("Верный прицел", "will", "accuracy", "mark"),
        ("Весомый удар", "will", "power", "slow"),
        ("Попутный ветер", "will", "haste", "anchor"),
        ("Рука мастера", "will", "craft", "clarity"),
        ("Сращивание вещи", "will", "repair", "craft"),
        ("Сумеречная завеса", "will", "conceal", "perception"),
        ("Пространственный шаг", "will", "travel", "slow"),
        ("Размыкание чар", "will", "drain_mp", "dispel"),
    ],
}
SCHOOLS = dict(
    attack="Разрушение", defense="Обереги", healing="Жизнь", research="Познание", support="Воля"
)
RECIPE_NAMES = {
    "smithing": "Ковка",
    "alchemy": "Составление",
    "repair": "Восстановление",
    "production": "Обработка",
}


def build():
    records = []

    def add(kind, group, id, name, **data):
        records.append(
            {
                "id": id,
                "kind": kind,
                "category": group,
                "name": name,
                "description": data.pop(
                    "description", name + ". Действие зависит от цели, условий и расхода ресурсов."
                ),
                **data,
            }
        )

    for m, name in enumerate(MATERIALS):
        for p, process in enumerate(PROCESSES):
            id = f"mat_{m}_{p}"
            add(
                "material",
                "materials",
                id,
                f"{name}: {process}",
                base=m,
                process=p,
                hardness=2 + m % 4 + p,
                elasticity=1 + (m + 3 * p) % 8,
                conductivity=(m + p) % 5,
                mass_g=50 + 25 * ((m + 2 * p) % 8),
                durability=18 + m + 3 * p,
                price_cp=8 + 4 * m + 7 * p,
                level=max(1, 2 * p - 1),
                obtain="gather" if not p else "production",
            )

    for family, (name, die, hands) in WEAPONS.items():
        for m in range(10):
            for design, style in enumerate(DESIGNS):
                add(
                    "weapon",
                    family,
                    f"gear_{family}_{m}_{design}",
                    f"{name} «{style}»: {MATERIALS[m]}",
                    material=f"mat_{m}_{design}",
                    dice=die,
                    hands=hands,
                    damage_type=("physical", "fire", "cold", "lightning")[m % 4],
                    trait=(
                        "guard",
                        "precision",
                        "power",
                        "parry",
                        "weaken",
                        "bleed",
                        "slow",
                        "mark",
                    )[design],
                    requirement=8 + (design % 4) * 2,
                    level=max(1, 2 * design - 1),
                    mass_g=200 + 100 * hands + 45 * m - 15 * design,
                    durability=20 + 2 * m + 4 * design,
                    price_cp=70 + 18 * m + 35 * design,
                    stamina=1 + hands + int(m > 6),
                    range=1 if family in ("longbow", "crossbow") else 0,
                )
    for family, name in (
        ("light", "Лёгкий доспех"),
        ("medium", "Средний доспех"),
        ("heavy", "Тяжёлый доспех"),
        ("shield", "Щит"),
    ):
        for m in range(10):
            for design, style in enumerate(DESIGNS):
                add(
                    "armour",
                    family,
                    f"gear_{family}_{m}_{design}",
                    f"{name} «{style}»: {MATERIALS[m]}",
                    material=f"mat_{m}_{design}",
                    defence={"light": 11, "medium": 13, "heavy": 16, "shield": 2}[family],
                    dex_cap={"light": 5, "medium": 2, "heavy": 0, "shield": 0}[family],
                    resistance=("physical", "fire", "cold", "lightning", "shadow")[m % 5],
                    trait=(
                        "guard",
                        "precision",
                        "power",
                        "parry",
                        "weaken",
                        "bleed",
                        "slow",
                        "mark",
                    )[design],
                    requirement=8 + (4 if family == "heavy" else 0),
                    level=max(1, 2 * design - 1),
                    mass_g=500 + 150 * m + 100 * design,
                    durability=25 + 2 * m + 4 * design,
                    price_cp=90 + 20 * m + 40 * design,
                )

    for group, profiles in PROFILES.items():
        for p, (name, element, primary, secondary) in enumerate(profiles):
            for _i, (mode, (form, targets, distance, minutes, extra, hp_cost)) in enumerate(
                MODES.items()
            ):
                id = f"spell_{group}_{p}_{mode}"
                if (group, p, mode) == ("attack", 0, "direct"):
                    id = "bolt"
                if (group, p, mode) == ("healing", 0, "direct"):
                    id = "heal"
                if (group, p, mode) == ("research", 0, "direct"):
                    id = "light"
                circle = min(5, 1 + p // 2 + int(mode in ("chain", "area", "sustained")))
                mp = max(1, 2 + circle * 2 + extra)
                if id == "light":
                    mp = 1
                if id in ("bolt", "heal"):
                    mp = 3
                add(
                    "spell",
                    group,
                    id,
                    f"{name}: {form}",
                    school=SCHOOLS[group],
                    circle=circle,
                    level=(1, 3, 5, 9, 13)[circle - 1],
                    mp=mp,
                    hp_cost=hp_cost,
                    range=distance,
                    target_limit=targets,
                    duration=2 + circle,
                    minutes=minutes,
                    mode=mode,
                    element=element,
                    effects=[
                        {"op": primary, "power": circle + 1},
                        {"op": secondary, "power": circle},
                    ],
                    dice=f"{circle}d6" if group == "attack" else f"{circle}d4",
                    acquire="research_or_teacher",
                    limitations=["confirmed_targets", "finite_resources"],
                )

    for ci, class_id in enumerate(CLASSES):
        group = ("attack", "attack", "support", "research", "healing", "support")[ci]
        for p, (name, element, primary, secondary) in enumerate(PROFILES[group]):
            for i, (mode, (form, targets, distance, minutes, extra, hp_cost)) in enumerate(
                MODES.items()
            ):
                add(
                    "talent",
                    class_id,
                    f"talent_{class_id}_{p}_{mode}",
                    f"{CLASS_NAMES[ci]}: {name} — {form}",
                    level=(2, 5, 10, 15)[p // 2],
                    class_id=class_id,
                    cost_st=3 + p + max(0, extra),
                    cooldown=2 + i % 3,
                    range=distance,
                    target_limit=targets,
                    duration=2 + p // 2,
                    minutes=minutes,
                    hp_cost=hp_cost,
                    mode=mode,
                    element=element,
                    effects=[
                        {"op": primary, "power": 1 + p // 2},
                        {"op": secondary, "power": 1 + p // 3},
                    ],
                    dice=f"{1 + p // 3}d6",
                    role=group,
                )

    spells = [r for r in records if r["kind"] == "spell"]
    for group in ("potions", "dressings", "scrolls"):
        for p in range(8):
            for grade in range(10):
                spell = (
                    spells[p * 10 + grade]
                    if group == "scrolls"
                    else next(
                        r
                        for r in spells
                        if r["category"] == "healing"
                        and r["mode"] == "direct"
                        and r["effects"][0]["op"] == PROFILES["healing"][p][2]
                        and r["effects"][1]["op"] == PROFILES["healing"][p][3]
                    )
                )
                # The selected technique and treatment restrictions affect actual use.
                effect = [dict(e) for e in spell["effects"]]
                if group != "scrolls":
                    profile = PROFILES["healing"][p]
                    effect = [
                        {"op": profile[2], "power": 1 + grade // 3},
                        {"op": profile[3], "power": 1 + grade // 4},
                    ]
                form_name = "Перевязка" if group == "dressings" else "Снадобье"
                item_name = (
                    ("Свиток: " + spell["name"])
                    if group == "scrolls"
                    else (f"{form_name}: {PROFILES['healing'][p][0]} — {grade + 1} ступень")
                )
                add(
                    "consumable",
                    group,
                    f"use_{group}_{p}_{grade}",
                    item_name,
                    spell_id=spell["id"],
                    effects=effect,
                    mode=spell["mode"] if group == "scrolls" else "direct",
                    level=max(1, grade * 2),
                    duration=2 + grade,
                    dice=f"{1 + grade // 3}d4",
                    minutes=10 if group == "dressings" else 1,
                    combat=group != "dressings",
                    targets=1,
                    material=f"mat_{p % 10}_{grade % 8}",
                    price_cp=30 + grade * 30 + p * 7,
                    mass_g=30 + p * 5 + grade * 2,
                )

    for p, (name, effect, element) in enumerate(
        (
            ("Утяжелённое", "power", "physical"),
            ("Бронебойное", "pierce", "physical"),
            ("Зазубренное", "bleed", "physical"),
            ("Оглушающее", "stagger", "thunder"),
            ("Горящее", "burn", "fire"),
            ("Морозное", "slow", "cold"),
            ("Глушащее", "drain_mp", "shadow"),
            ("Опутывающее", "net", "physical"),
        )
    ):
        for m in range(10):
            add(
                "consumable",
                "ammunition",
                f"use_ammunition_{p}_{m}",
                f"Оперённый снаряд: {name} — {MATERIALS[m]}",
                material=f"mat_{m}_{p}",
                effect=effect,
                element=element,
                power=1 + m // 4,
                batch=6 + p,
                level=max(1, 2 * p - 1),
                mass_g=10 + 2 * m + p,
                price_cp=2 + m + p * 2,
            )

    for m in range(10):
        for p, process in enumerate(PROCESSES):
            add(
                "household",
                "household",
                f"house_{m}_{p}",
                f"Походный прибор: {MATERIALS[m]} — {process}",
                material=f"mat_{m}_{p}",
                level=max(1, 2 * p - 1),
                capability=(
                    "tools",
                    "forge",
                    "alchemy",
                    "workbench",
                    "light",
                    "container",
                    "camp",
                    "survey",
                )[p],
                strength=1 + m % 4,
                durability=20 + 4 * m + 3 * p,
                price_cp=40 + 20 * m + 18 * p,
                mass_g=100 + 25 * m + 45 * p,
            )

    for direction, name in RECIPE_NAMES.items():
        for m in range(10):
            for p, process in enumerate(PROCESSES):
                material = f"mat_{m}_{p}"
                outputs = []
                if direction == "smithing":
                    outputs = [
                        r["id"]
                        for r in records
                        if r["kind"] in ("weapon", "armour") and r["material"] == material
                    ]
                elif direction == "alchemy":
                    outputs = [
                        r["id"]
                        for r in records
                        if r["kind"] == "consumable"
                        and r["category"] != "scrolls"
                        and r["material"] == material
                    ]
                    if not outputs:
                        outputs = [f"use_potions_{m % 8}_{p}"]
                elif direction == "production":
                    outputs = ([material] if p else []) + [
                        f"house_{m}_{p}",
                        f"use_ammunition_{p}_{m}",
                    ]
                    outputs += [
                        r["id"]
                        for r in records
                        if r["kind"] == "consumable"
                        and r["category"] == "scrolls"
                        and r["material"] == material
                    ]
                add(
                    "recipe",
                    direction,
                    f"recipe_{direction}_{m}_{p}",
                    f"{name}: {MATERIALS[m]} — {process}",
                    level=max(1, 2 * p - 1),
                    outputs=outputs,
                    ingredients={f"mat_{m}_{max(0, p - 1)}": 2 + p % 3},
                    tools="tools",
                    station={
                        "smithing": "forge",
                        "alchemy": "alchemy",
                        "repair": "tools",
                        "production": "workbench",
                    }[direction],
                    minutes=10 + 5 * p + m,
                    dc=(5, 10, 15, 20)[min(3, p // 2)],
                    task={"production": "repair"}.get(direction, direction),
                    repair_power=5 + p + m % 3,
                    compatible_material=m,
                    failure="consume_one_material_and_time",
                    quality_cap=1 + p // 3,
                )

    behaviors = (
        "hunter",
        "guardian",
        "skirmisher",
        "archer",
        "caster",
        "healer",
        "scavenger",
        "berserker",
    )
    habitats = (
        "Лес",
        "Степь",
        "Горы",
        "Болота",
        "Руины",
        "Пустыня",
        "Пещеры",
        "Берег",
        "Тундра",
        "Город",
    )
    for family, title in (
        ("beast", "Зверь"),
        ("humanoid", "Противник"),
        ("undead", "Нежить"),
        ("arcane", "Магическое создание"),
    ):
        for role, behavior in enumerate(behaviors):
            for habitat in range(10):
                danger = 1 + role + habitat
                add(
                    "creature",
                    family,
                    f"creature_{family}_{role}_{habitat}",
                    f"{title}: {DESIGNS[role]} — {habitats[habitat]}",
                    level=danger,
                    hp=10 + 4 * danger,
                    defence=10 + danger // 3,
                    strength=10 + min(10, role + habitat),
                    dexterity=10 + min(8, habitat),
                    dice=f"{1 + danger // 8}d6",
                    weapon="longbow" if behavior == "archer" else "dagger",
                    behavior=behavior,
                    habitat=habitat,
                    morale=2 + role % 4,
                    resistance=("physical", "fire", "cold", "lightning", "shadow")[habitat % 5],
                    vulnerability=("radiant", "nature", "thunder", "cold", "fire")[role % 5],
                    skill_effect=(
                        "bleed",
                        "guard",
                        "slow",
                        "mark",
                        "burn",
                        "heal",
                        "weaken",
                        "power",
                    )[role],
                    loot={f"mat_{habitat}_0": 1 + role % 2},
                    xp=30 + 15 * danger,
                    peaceful=("food", "warning", "bargain", "retreat")[habitat % 4],
                    spawn_cost=1 + danger // 4,
                )

    actions = {
        "economic": (
            "delivery",
            "production",
            "wage",
            "demand",
            "caravan",
            "maintenance",
            "closure",
            "commission",
        ),
        "political": (
            "levy",
            "aid",
            "treaty",
            "embargo",
            "territory",
            "rotation",
            "office",
            "subsidy",
        ),
        "social": (
            "cooperate",
            "share_food",
            "exchange_news",
            "apprentice",
            "dispute",
            "relocate",
            "assist",
            "celebrate",
        ),
        "military": (
            "patrol",
            "raid",
            "fortify",
            "recruit",
            "resupply",
            "withdraw",
            "rescue",
            "truce",
        ),
        "natural": ("rain", "drought", "fog", "storm", "growth", "frost", "flood", "thaw"),
    }
    for group, ops in actions.items():
        for p, op in enumerate(ops):
            for m in range(10):
                event_names = {
                    "economic": (
                        "Поставка",
                        "Производство",
                        "Жалованье",
                        "Спрос",
                        "Караван",
                        "Обслуживание",
                        "Закрытие лавки",
                        "Заказ",
                    ),
                    "political": (
                        "Сбор",
                        "Помощь",
                        "Договор",
                        "Эмбарго",
                        "Территория",
                        "Смена стражи",
                        "Новая должность",
                        "Субсидия",
                    ),
                    "social": (
                        "Сотрудничество",
                        "Обмен пищей",
                        "Обмен новостями",
                        "Обучение",
                        "Спор",
                        "Переезд",
                        "Поддержка",
                        "Праздник",
                    ),
                    "military": (
                        "Патруль",
                        "Набег",
                        "Укрепление",
                        "Набор",
                        "Снабжение",
                        "Отступление",
                        "Спасение",
                        "Перемирие",
                    ),
                    "natural": (
                        "Дождь",
                        "Засуха",
                        "Туман",
                        "Буря",
                        "Рост",
                        "Заморозки",
                        "Паводок",
                        "Оттепель",
                    ),
                }
                add(
                    "event",
                    group,
                    f"event_{group}_{p}_{m}",
                    f"{event_names[group][p]}: {MATERIALS[m]}",
                    op=op,
                    resource=f"mat_{m}_0",
                    amount=1 + (m + p) % 3,
                    money=2 + 3 * m + p,
                    duration=60 + 30 * p,
                    threshold=1 + m % 4,
                    season=m % 4,
                    role=p % 8,
                    cooldown_days=1 + p % 3,
                    conditions=["living_witness", "finite_supply"],
                    scope="registered_npcs_only",
                    role_description=op,
                )
    return {"schema": "game-catalog-1", "records": records}
