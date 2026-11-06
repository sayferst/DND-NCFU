"""Reproducible original homebrew variants, not scraped or human-reviewed content."""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rpg_vkr.world_library.model import digest, dump, validate_bundle  # noqa: E402

OUT = ROOT / "data/world_library"


def text(maximum=400, minimum=1):
    return {"type": "string", "minLength": minimum, "maxLength": maximum}


def number(low=0, high=100000):
    return {"type": "integer", "minimum": low, "maximum": high}


def obj(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def array(items, maximum=24):
    return {"type": "array", "items": items, "maxItems": maximum}


ID = text(64)
ID["pattern"] = "[a-z][a-z0-9_]{0,63}"
ACTOR = {
    "hp_max": number(1, 820),
    "level": number(1, 20),
    "species": ID,
    "profession": text(),
    "social_status": text(),
    "beliefs": text(),
    "appearance": text(),
    "motivation": text(),
    "biography": text(1200),
    "age_years": number(1, 1000),
    "surname": text(),
    "initial_mood": {"type": "string", "enum": ["calm", "wary", "angry"]},
    "mood_transitions": array(obj({"from": text(), "event": text(), "to": text()}), 6),
    "territory": text(),
    "diet": text(),
    "tactics": text(),
}
PHYSICAL = {
    "mass_g": number(1, 1000000),
    "durability": number(1, 200),
    "quality": number(1, 5),
    "purpose": text(),
    "history": text(800),
}
PROFILES = {
    "weapon": PHYSICAL
    | {
        "damage_count": number(1, 2),
        "damage_die": number(2, 12),
        "penetration": number(0, 6),
        "hands": number(1, 2),
    },
    "armour": PHYSICAL | {"defence": number(0, 8), "slot": text()},
    "ammunition": PHYSICAL | {"compatible": text(), "penetration": number(0, 4)},
    "tool": PHYSICAL | {"proficiency": text()},
    "medicine": PHYSICAL
    | {"effect": text(), "potency": number(1, 8), "fictional": {"type": "boolean"}},
    "poison": PHYSICAL
    | {"effect": text(), "potency": number(1, 8), "fictional": {"type": "boolean"}},
    "food": PHYSICAL | {"nutrition": number(1, 10), "shelf_days": number(1, 365)},
    "ingredient": PHYSICAL | {"habitat": text(), "processing": text()},
    "plant": PHYSICAL | {"habitat": text(), "season": text(), "harvest": text()},
    "ore": PHYSICAL | {"deposit": text(), "yield_percent": number(1, 95)},
    "material": PHYSICAL | {"family": text(), "processing": text()},
    "book": PHYSICAL | {"subject": text(), "author": text()},
    "quest": PHYSICAL | {"objective": text(), "issuer": text()},
    "npc": ACTOR,
    "creature": ACTOR,
    "boss": ACTOR,
    "spell": {
        "school": text(),
        "nature": text(),
        "level": number(0, 9),
        "mp": number(1, 30),
        "duration_turns": number(0, 100),
        "components": array(text(), 5),
        "effect": text(),
        "counterplay": text(),
    },
    "rune": PHYSICAL | {"trigger": text(), "charges": number(1, 3)},
    "scroll": PHYSICAL | {"charges": number(1, 1)},
    "combination": {"level": number(1, 9), "mp": number(2, 30), "effect": text()},
    "skill": {"ability": text(), "use": text(), "limit": text()},
    "race": {"lifespan": number(20, 1000), "size": text(), "culture": text(), "trait": text()},
    "recipe": {
        "minutes": number(1, 10000),
        "difficulty": number(5, 25),
        "labour_cp": number(),
        "method": text(),
        "mode": {"type": "string", "enum": ["craft", "salvage"]},
    },
}


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    link = obj(
        {
            "relation": {
                "type": "string",
                "enum": [
                    "component",
                    "input",
                    "output",
                    "spell",
                    "combines",
                    "species",
                    "starting_inventory",
                    "parent",
                    "child",
                ],
            },
            "target": ID,
            "quantity": number(1, 1000),
            "role": text(),
        }
    )
    record_schema = obj(
        {
            "id": ID,
            "name": text(100),
            "profile": {"type": "string", "enum": list(PROFILES)},
            "category": text(100),
            "description": text(1800, 40),
            "price_cp": number(0, 1000000),
            "attributes": {"type": "object"},
            "links": array(link, 512),
            "provenance": obj(
                {
                    "origin": {"type": "string", "enum": ["invented/homebrew"]},
                    "source": text(),
                    "generator": text(),
                    "review": {"type": "string", "enum": ["unreviewed", "engineer-reviewed"]},
                }
            ),
        }
    )
    schema = {"record": record_schema} | {k: obj(v) for k, v in PROFILES.items()}
    for profile in ("npc", "creature", "boss"):
        schema[profile]["properties"].update(
            abilities=obj(
                {
                    k: number(1, 30)
                    for k in (
                        "strength",
                        "dexterity",
                        "constitution",
                        "intelligence",
                        "wisdom",
                        "charisma",
                    )
                }
            ),
            armour_class=number(1, 25),
            damage_dice={
                "type": "string",
                "maxLength": 40,
                "pattern": r"[1-9][0-9]?d(?:4|6|8|10|12)(?:[+-][0-9]{1,2})?",
            },
        )  # Additive fields: published older actor records remain valid.
    from import_rpgd100_facts import extend_schema

    extend_schema(schema)
    for value in schema.values():
        value["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    (OUT / "schemas.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    records = []

    def add(key, name, profile, attributes, description, price=0, links=None):
        if profile in {"npc", "creature", "boss"}:
            attributes = dict(attributes)
            code = int(digest({"actor": key})[:8], 16)
            abilities = {
                k: 8 + ((code >> (n * 3)) % 6)
                for n, k in enumerate(
                    (
                        "strength",
                        "dexterity",
                        "constitution",
                        "intelligence",
                        "wisdom",
                        "charisma",
                    )
                )
            }
            if profile == "npc":
                job = attributes["profession"].casefold()
                if any(t in job for t in ("кузнец", "рудокоп", "лесоруб", "каменщик", "страж")):
                    abilities["strength"] += 3
                if any(t in job for t in ("лекарь", "травник", "учитель", "писец", "алхимик")):
                    abilities["intelligence"] += 3
                if any(t in job for t in ("торговец", "трактирщик", "певец")):
                    abilities["charisma"] += 3
                natural_armour, dice = 0, "1d4"
            else:
                boss = profile == "boss"
                abilities.update(
                    strength=14 if not boss else 18 + attributes["level"] // 4,
                    constitution=12 + attributes["level"] // 3,
                    intelligence=3,
                    wisdom=12,
                )
                if "мотылёк" in name.casefold():
                    abilities.update(strength=3 if not boss else 10, dexterity=16)
                if "страж" in name.casefold():
                    abilities.update(strength=18 if not boss else 22, intelligence=8)
                natural_armour = 3 if any(t in name.casefold() for t in ("краб", "каменный")) else 1
                dice = "2d6" if boss else "1d4" if "мотылёк" in name.casefold() else "1d6"
            attributes.update(
                abilities=abilities,
                damage_dice=dice,
                armour_class=10 + (abilities["dexterity"] - 10) // 2 + natural_armour,
            )
        group = (
            "actors"
            if profile in {"npc", "creature", "boss", "race"}
            else "magic"
            if profile in {"spell", "rune", "scroll", "combination"}
            else "knowledge"
            if profile in {"skill", "recipe"}
            else "physical"
        )
        row = {
            "id": "wl_" + key,
            "name": name,
            "profile": profile,
            "category": group + "." + profile,
            "description": description,
            "price_cp": price,
            "attributes": attributes,
            "links": links or [],
            "provenance": {
                "origin": "invented/homebrew",
                "source": "DND-NCFU original frontier setting",
                "generator": (
                    "world-library-4"
                    if profile in {"npc", "creature", "boss"}
                    else "world-library-3"
                    if profile in {"food", "medicine", "poison", "book", "quest"}
                    else "world-library-2"
                ),
                "review": "unreviewed",
            },
        }
        records.append(row)
        return row["id"]

    def ref(target, relation="component", quantity=1, role="основной материал"):
        return {"relation": relation, "target": target, "quantity": quantity, "role": role}

    def npc_inventory(profession, job_index, region_index, shift):
        def held(key, role, quantity=1):
            return ref(f"wl_{key}_{region_index}", "starting_inventory", quantity, role)

        stock = [held(f"food_{(job_index + shift) % 8}", "личный дорожный запас", 2)]
        if profession == "егерь":
            return stock + [
                held("weapon_10", "охотничий лук"),
                held("ammunition_0", "конечный запас стрел", 12),
            ]
        if profession == "страж":
            return stock + [
                held("weapon_3", "служебное копьё"),
                held("armour_2", "личная кольчуга"),
            ]
        if profession == "лекарь":
            return stock + [held("medicine_0", "запас ухода за ранеными", 2)]
        if profession in {"певец", "картограф", "архивист", "учитель"}:
            book = 4 if profession == "певец" else 1 if profession == "картограф" else 5
            return stock + [held(f"book_{book}", "рабочие записи")]
        tools = {
            0: 1,
            1: 8,
            6: 11,
            7: 11,
            8: 5,
            9: 9,
            10: 10,
            11: 11,
            12: 10,
            13: 2,
            16: 0,
            18: 4,
            19: 11,
        }
        return stock + [
            held(f"tool_{tools.get(job_index, 0)}", "принадлежность по профессии"),
            held("weapon_8", "рабочий нож"),
        ]

    def physical(i, purpose, mass=500):
        return {
            "mass_g": mass,
            "durability": 30 + i % 5 * 10,
            "quality": 1 + i % 5,
            "purpose": purpose,
            "history": (
                "Местное производство Пограничья; уникальная история "
                "появляется только в конкретном мире."
            ),
        }

    materials = []
    for i, (name, family, process) in enumerate(
        [
            ("Ясень", "wood", "сушка в проветриваемом сарае"),
            ("Тис", "wood", "медленная сушка заготовок"),
            ("Дуб", "wood", "выдержка и распил"),
            ("Берёза", "wood", "сушка и строгание"),
            ("Лён", "fibre", "прядение волокон"),
            ("Пенька", "fibre", "свивание волокон"),
            ("Кожа", "hide", "дубление"),
            ("Шерсть", "fibre", "прядение и валяние"),
            ("Железо", "metal", "ковка"),
            ("Сталь", "metal", "кузнечная обработка"),
            ("Бронза", "metal", "литьё"),
            ("Медь", "metal", "чеканка"),
            ("Глина", "earth", "обжиг"),
            ("Стекло", "glass", "выдувание"),
            ("Кость", "bone", "резьба"),
            ("Камень", "stone", "шлифовка"),
        ]
    ):
        materials.append(
            add(
                f"material_{i}",
                name,
                "material",
                physical(i, "Сырьё для ремесла", 1000) | {"family": family, "processing": process},
                (
                    f"{name} — ремесленная партия местного происхождения. "
                    f"Обработка: {process}. Качество партии определяет отходы; "
                    f"добыча и расход учитываются движком, а не описанием."
                ),
                10 + i * 2,
            )
        )
    regions = [
        "Северная переправа",
        "Ольховая долина",
        "Солёный берег",
        "Меловой кряж",
        "Старый тракт",
        "Медное озеро",
        "Ветреная степь",
        "Туманные острова",
        "Глубокий бор",
        "Каменная слобода",
    ]
    species = []
    for i, name in enumerate(
        [
            "Люди переправ",
            "Сумеречные эльфы",
            "Каменные дварфы",
            "Луговые полурослики",
            "Пепельные орки",
            "Речные гномы",
            "Чешуйчатые странники",
            "Рогатые хранители",
        ]
    ):
        species.append(
            add(
                f"race_{i}",
                name,
                "race",
                {
                    "lifespan": 90 + i * 20,
                    "size": "средний" if i not in {3, 5} else "малый",
                    "culture": (
                        "Культурные традиции зависят от поселения, а не определяют "
                        "характер личности."
                    ),
                    "trait": "Предпочитают освоенные пути; числовой бонус не назначен.",
                },
                (
                    f"{name} — авторский вид Пограничья. Представители живут в "
                    f"смешанных общинах, выбирают разные профессии и убеждения. "
                    f"Культура не задаёт врождённую враждебность."
                ),
            )
        )
    for i, region in enumerate(regions):
        for j, name in enumerate(
            ["Железняк", "Медный колчедан", "Оловянная руда", "Серебристый сланец"]
        ):
            add(
                f"ore_{i}_{j}",
                f"{name}: {region}",
                "ore",
                physical(j, "Переработка в мастерской", 2000)
                | {"deposit": region, "yield_percent": 25 + j * 10},
                (
                    f"{name} из местности «{region}» содержит заметную пустую "
                    f"породу. Перед работой мастер оценивает выход полезного "
                    f"материала; остаток не исчезает и может быть использован как "
                    f"засыпка."
                ),
                12 + j * 8,
            )
        for j, name in enumerate(
            [
                "Синелист",
                "Сонная мята",
                "Янтарный мох",
                "Речной вереск",
                "Лунный тростник",
                "Красная кислица",
                "Колючая полынь",
                "Пепельный гриб",
            ]
        ):
            plant = add(
                f"plant_{i}_{j}",
                f"{name}: {region}",
                "plant",
                physical(j, "Фантазийный растительный ресурс", 100)
                | {
                    "habitat": region,
                    "season": ["весна", "лето", "осень", "зима"][j % 4],
                    "harvest": "Сбор листьев без уничтожения корня; объём узла конечен.",
                },
                (
                    f"{name} растёт в местности «{region}». Его узнают по "
                    f"контрастным жилкам и пряному вымышленному запаху. Это игровое "
                    f"растение; свойства не описывают реальные лечебные или "
                    f"токсичные вещества."
                ),
                5 + j,
            )
            add(
                f"ingredient_{i}_{j}",
                f"Высушенный {name.lower()}: {region}",
                "ingredient",
                physical(j, "Компонент авторских рецептов", 50)
                | {"habitat": region, "processing": "Сушка; правила выхода определяет рецепт."},
                (
                    f"Подписанный пакет растения «{name}» из местности «{region}». "
                    f"Потеря влаги облегчает перевозку, но требует сухого хранения. "
                    f"Игровые эффекты возможны только через проверенный рецепт."
                ),
                8 + j,
                [ref(plant)],
            )
    forms = {
        "weapon": [
            "Короткий меч",
            "Длинный меч",
            "Тесак",
            "Копьё",
            "Пика",
            "Топор",
            "Молот",
            "Булава",
            "Кинжал",
            "Посох",
            "Короткий лук",
            "Длинный лук",
            "Арбалет",
            "Праща",
            "Трезубец",
            "Алебарда",
        ],
        "armour": [
            "Стёганка",
            "Кожаный жилет",
            "Кольчужная рубаха",
            "Ламеллярный панцирь",
            "Нагрудник",
            "Шлем",
            "Наручи",
            "Щит",
        ],
        "ammunition": ["Стрела", "Арбалетный болт", "Пращный снаряд", "Тренировочная стрела"],
        "tool": [
            "Набор плотника",
            "Набор кузнеца",
            "Набор ткача",
            "Набор картографа",
            "Набор сапожника",
            "Набор гончара",
            "Набор переплётчика",
            "Набор ювелира",
            "Рыболовная снасть",
            "Счётная доска",
            "Полевой котелок",
            "Фонарь",
        ],
        "medicine": [
            "Повязка синелиста",
            "Бальзам янтарного мха",
            "Настой лунного тростника",
            "Пакет полевого ухода",
        ],
        "poison": ["Сумеречная пыль", "Сонный туман", "Чернильная метка", "Пепельная слабость"],
        "food": [
            "Походные сухари",
            "Сушёные яблоки",
            "Сыр в воске",
            "Копчёная рыба",
            "Овсяная смесь",
            "Бобовая похлёбка",
            "Лепёшка",
            "Ореховая паста",
        ],
        "book": [
            "Записки переправщика",
            "Атлас старых дорог",
            "Книга долгов",
            "Дневник старателя",
            "Сборник песен",
            "Реестр мастерской",
            "Полевой определитель",
            "Хроника заставы",
        ],
        "quest": [
            "Запечатанное письмо",
            "Половина медальона",
            "Сломанная печать",
            "Бирка пропавшего обоза",
            "Ключ от архива",
            "Карта тайника",
            "Свидетельская запись",
            "Знак доверия",
        ],
    }
    items = []
    for profile, names in forms.items():
        for j, name in enumerate(names):
            for i, region in enumerate(regions):
                a = physical(
                    i,
                    name,
                    100 if profile in {"medicine", "poison", "ammunition"} else 500 + j * 100,
                )
                links = []
                if profile == "weapon":
                    a |= {
                        "damage_count": 1,
                        "damage_die": [4, 6, 8][j % 3],
                        "penetration": j % 3,
                        "hands": 2 if j in {4, 10, 11, 12, 15} else 1,
                    }
                    wood = materials[i % 4]
                    links = (
                        [
                            ref(wood, role="плечи и рукоять"),
                            ref(materials[4 + i % 2], role="тетива и обмотка"),
                        ]
                        if j in {10, 11}
                        else [ref(materials[9], role="рабочая часть"), ref(wood, role="рукоять")]
                    )
                elif profile == "armour":
                    a |= {"defence": 1 + j % 5, "slot": "shield" if j == 7 else "body"}
                    links = [
                        ref(materials[6], role="подкладка"),
                        ref(materials[9], role="защитные детали"),
                    ]
                elif profile == "ammunition":
                    a |= {
                        "compatible": "праща" if j == 2 else "арбалет" if j == 1 else "лук",
                        "penetration": j % 3,
                    }
                    links = [ref(materials[0]), ref(materials[8], role="наконечник")]
                elif profile == "tool":
                    a |= {"proficiency": name}
                    links = [ref(materials[9]), ref(materials[0], role="рукояти")]
                elif profile in {"medicine", "poison"}:
                    a |= {
                        "effect": (
                            "Восстанавливает 2 × силу HP живой цели; расходуется одна единица."
                            if profile == "medicine"
                            else "Вымышленный боевой порошок: проверка нанесения, затем стойкость "
                            "Сл 10 + сила; при провале цели 1d4 + сила урона ядом. "
                            "Единица расходуется при попытке."
                        ),
                        "potency": 1 + j,
                        "fictional": True,
                    }
                    links = [ref(f"wl_ingredient_{i}_{j}")]
                elif profile == "food":
                    a |= {"nutrition": 1 + j % 3, "shelf_days": 3 + j * 7}
                elif profile == "book":
                    a |= {"subject": name, "author": f"Архивная артель: {region}"}
                    links = [ref(materials[4], role="листы"), ref(materials[6], role="переплёт")]
                elif profile == "quest":
                    a |= {
                        "objective": (
                            "Осмотреть и установить происхождение; награда не "
                            "гарантируется описанием."
                        ),
                        "issuer": region,
                    }
                price = 50 + j * 15 + i * 2
                finish = [
                    "Ремонтопригодные детали облегчают уход",
                    "Плотная упаковка защищает в дороге",
                    "Усиленные края рассчитаны на частое использование",
                    "Простая отделка удобна в полевых условиях",
                    "Аккуратная подгонка уменьшает люфт",
                ][i % 5]
                item = add(
                    f"{profile}_{j}_{i}",
                    f"{name}: {region}",
                    profile,
                    a,
                    (
                        f"{name}, изготовлено для местности «{region}». Мастерская "
                        f"использует клеймо в форме "
                        f"{['моста', 'листа', 'волны', 'башни', 'колеса'][i % 5]}. "
                        f"{finish}. "
                        f"{a['purpose']}. Региональный вариант не даёт скрытых бонусов."
                    ),
                    price,
                    links,
                )
                items.append(item)
                if profile in {"weapon", "armour", "tool"}:
                    inputs = links or [ref(materials[0])]
                    add(
                        f"recipe_{profile}_{j}_{i}",
                        f"Изготовление: {name}, {region}",
                        "recipe",
                        {
                            "minutes": 60 + j * 15,
                            "difficulty": 10 + j % 5,
                            "labour_cp": price,
                            "method": (
                                "Работа в оснащённой мастерской; обработчик проверяет "
                                "материалы, инструменты и время."
                            ),
                            "mode": "craft",
                        },
                        (
                            f"Ремесленный проект «{name}» для местности «{region}». "
                            f"Материалы списываются до выдачи результата в одной "
                            f"транзакции. Описание не разрешает бесплатное создание и не "
                            f"заменяет проверку навыка."
                        ),
                        links=[dict(x, relation="input") for x in inputs] + [ref(item, "output")],
                    )
                    add(
                        f"salvage_{profile}_{j}_{i}",
                        f"Разборка: {name}, {region}",
                        "recipe",
                        {
                            "minutes": 30,
                            "difficulty": 10,
                            "labour_cp": 0,
                            "method": (
                                "Возвращается лишь один основной материал; изношенные части "
                                "теряются."
                            ),
                            "mode": "salvage",
                        },
                        (
                            f"Разборка предмета «{name}» из местности «{region}». Исходный "
                            f"экземпляр расходуется полностью; восстановление целого "
                            f"предмета бесплатно невозможно. Движок должен проверить "
                            f"владение и состояние."
                        ),
                        links=[ref(item, "input"), ref(inputs[0]["target"], "output")],
                    )
    professions = [
        "кузнец",
        "переправщик",
        "лекарь",
        "картограф",
        "архивист",
        "страж",
        "пастух",
        "рудокоп",
        "гончар",
        "торговец",
        "садовник",
        "посыльный",
        "повар",
        "ткач",
        "егерь",
        "учитель",
        "каменщик",
        "певец",
        "сапожник",
        "смотритель",
    ]
    names = [
        "Мира",
        "Терен",
        "Вела",
        "Орин",
        "Нара",
        "Демир",
        "Илва",
        "Радан",
        "Сая",
        "Энна",
        "Борин",
        "Лея",
        "Нерис",
        "Фарен",
        "Аста",
        "Рем",
        "Юна",
        "Тави",
        "Кира",
        "Дален",
    ]
    for i, region in enumerate(regions):
        for j, profession in enumerate(professions):
            for shift in range(2):
                n = j + shift * 20
                history = (
                    "переехал после закрытия старой мастерской"
                    if shift
                    else "учился у родственника и остался помогать общине"
                )
                a = {
                    "hp_max": 12 + j % 5 * 3,
                    "level": 1 + j % 3,
                    "species": species[(i + j) % 8],
                    "profession": profession,
                    "social_status": [
                        "вольный горожанин",
                        "ученик артели",
                        "старший общины",
                        "наёмный работник",
                    ][n % 4],
                    "beliefs": [
                        "Слово следует подкреплять делом",
                        "Помощь соседям важнее престижа",
                        "Знания нужно сохранять",
                        "Долги требуют честного учёта",
                    ][n % 4],
                    "appearance": [
                        "Потёртый плащ и ровная осанка",
                        "Мозолистые руки и внимательный взгляд",
                        "Короткая стрижка и дорожная сумка",
                        "Седая прядь и значок артели",
                    ][n % 4],
                    "motivation": [
                        "Вернуть утраченное доверие артели",
                        "Собрать средства на общую мастерскую",
                        "Найти безопасный путь для обоза",
                        "Установить судьбу пропавшего родственника",
                    ][n % 4],
                    "biography": (
                        f"Поселение — {region}. Работает как {profession}; "
                        f"{history}. "
                        f"Недавний спор о поставках заставил внимательнее проверять "
                        f"обещания чужаков. Личные цели могут измениться после "
                        f"подтверждённых событий."
                    ),
                    "age_years": 22 + j * 2 + shift * 11,
                    "surname": ["Мостовой", "Вереск", "Камнев", "Листопад"][i % 4]
                    + (" Старший" if shift else " Младший"),
                    "initial_mood": "angry"
                    if (i + n) % 7 == 6
                    else ["wary", "calm", "angry"][(i + n) % 3],
                    "mood_transitions": []
                    if (i + n) % 7 == 6
                    else [
                        {
                            "from": "wary",
                            "event": "движок подтвердил выполненное обещание",
                            "to": "calm",
                        },
                        {
                            "from": "calm",
                            "event": "движок подтвердил кражу собственности",
                            "to": "angry",
                        },
                        {
                            "from": "wary",
                            "event": "движок подтвердил кражу собственности",
                            "to": "angry",
                        },
                        {
                            "from": "angry",
                            "event": "движок подтвердил выполненное обещание",
                            "to": "wary",
                        },
                    ],
                    "territory": region,
                    "diet": "Обычная местная пища",
                    "tactics": "Ищет помощь и пути отступления; не атакует без причины.",
                }
                add(
                    f"npc_{i}_{n}",
                    f"{names[j]} {a['surname']} ({region}, {profession})",
                    "npc",
                    a,
                    (
                        f"{names[j]} — {profession} из местности «{region}». "
                        f"{a['biography']} Главный мотив: {a['motivation'].lower()}. "
                        f"Начальное отношение осторожное; настроение и имущество "
                        f"существуют только у экземпляра в мире."
                    ),
                    links=[
                        ref(a["species"], "species"),
                        *npc_inventory(profession, j, i, shift),
                    ],
                )
        for j, beast in enumerate(
            [
                "Скальный волк",
                "Мшистый кабан",
                "Озёрный змей",
                "Пещерный краб",
                "Теневой мотылёк",
                "Рогатый падальщик",
                "Стеклянный паук",
                "Каменный страж",
            ]
        ):
            for boss in (False, True):
                profile = "boss" if boss else "creature"
                level = 6 + j if boss else 1 + j % 4
                history = (
                    "Занял заброшенную сторожевую башню"
                    if boss
                    else "освоил заросшие тропы после ухода людей"
                )
                a = {
                    "hp_max": 20 + level * 10,
                    "level": level,
                    "species": "fictional_beast",
                    "profession": "охрана территории" if boss else "поиск пищи",
                    "social_status": "одиночное существо",
                    "beliefs": "Поведение определяется наблюдаемыми потребностями.",
                    "appearance": f"{beast}; следы местной среды на покрове.",
                    "motivation": "Защищает гнездо; предпочитает отпугнуть нарушителя.",
                    "biography": (
                        f"Обитает в местности «{region}». "
                        f"{history}; "
                        f"встречи зависят от состояния локальной популяции."
                    ),
                    "age_years": 5 + j,
                    "surname": "Без родового имени",
                    "initial_mood": "wary",
                    "mood_transitions": [
                        {
                            "from": "wary",
                            "event": "вторжение в гнездо подтверждено движком",
                            "to": "angry",
                        }
                    ],
                    "territory": region,
                    "diet": "Вымышленная местная пищевая цепь",
                    "tactics": (
                        "Предупреждает, затем отступает к укрытию; фазы босса требуют обработчика."
                    ),
                }
                add(
                    f"{profile}_{i}_{j}",
                    f"{'Вожак: ' if boss else ''}{beast} ({region})",
                    profile,
                    a,
                    (
                        f"{beast} из местности «{region}». {a['biography']} "
                        f"{a['motivation']} Боевые показатели — стартовые авторские "
                        f"ориентиры; смена враждебности и добыча требуют "
                        f"подтверждённого события."
                    ),
                )
    spells = []
    for j, nature in enumerate(
        ["огонь", "вода", "камень", "ветер", "свет", "тень", "рост", "звук"]
    ):
        for level in range(1, 6):
            for mode, effect in enumerate(["преграда", "сигнал", "импульс", "покров"]):
                spell = add(
                    f"spell_{j}_{level}_{mode}",
                    f"{nature.capitalize()}: {effect}, ступень {level}",
                    "spell",
                    {
                        "school": ["воплощение", "преобразование", "ограждение", "иллюзия"][mode],
                        "nature": nature,
                        "level": level,
                        "mp": 2 * level + mode,
                        "duration_turns": 1 + level if mode != 2 else 0,
                        "components": ["жест", "слово", "фокус мастера"],
                        "rules": {
                            "operation": ["shield", "signal", "damage", "defence"][mode],
                            "element": [
                                "fire",
                                "cold",
                                "physical",
                                "thunder",
                                "radiant",
                                "necrotic",
                                "poison",
                                "thunder",
                            ][j],
                            "power": 2 * level if mode == 0 else 1 + level // 2,
                            "duration": 0 if mode == 2 else 1 + level,
                            "dice": f"{level}d4",
                        },
                        "effect": (
                            f"{effect.capitalize()} природы «{nature}»; интенсивность "
                            f"{level}. Обработчик library-magic-1: "
                            + [
                                f"защитный запас {2 * level}",
                                "световой сигнал без автоматического воздействия на NPC",
                                f"магическая атака, урон {level}d4",
                                f"бонус защиты {1 + level // 2}",
                            ][mode]
                        ),
                        "counterplay": (
                            "Эффект ограничен сроком; запас защиты расходуется уроном. "
                            "Эти авторские формулы не требуют концентрации."
                        ),
                    },
                    (
                        f"Авторская формула: {effect} природы «{nature}», ступень "
                        f"{level}. Длительность ограничена, стоимость MP обязательна. "
                        f"Более высокая ступень не отменяет укрытия, доступность цели "
                        f"или сопротивление. Это авторская формула, не правило SRD."
                    ),
                )
                spells.append(spell)
                for profile in ("rune", "scroll"):
                    a = physical(level, "Носитель магической формулы", 100) | {"charges": 1}
                    if profile == "rune":
                        a["trigger"] = "Подтверждённая активация владельцем"
                    add(
                        f"{profile}_{j}_{level}_{mode}",
                        f"{'Руна' if profile == 'rune' else 'Свиток'}: {nature}, {effect}, {level}",
                        profile,
                        a,
                        (
                            f"Однозарядный носитель формулы «{nature}: {effect}», ступень "
                            f"{level}. Заряд и владение проверяются по экземпляру. Надпись "
                            f"не позволяет обойти стоимость или создать дополнительный "
                            f"эффект."
                        ),
                        30 * level,
                        [ref(spell, "spell")],
                    )
    for i in range(0, len(spells), 2):
        children = [next(r for r in records if r["id"] == key) for key in spells[i : i + 2]]
        add(
            f"combination_{i}",
            f"Сплетение формул {i // 2 + 1}",
            "combination",
            {
                "level": max(r["attributes"]["level"] for r in children),
                "mp": sum(r["attributes"]["mp"] for r in children),
                "effect": "Две связанные формулы исполняются по порядку за их суммарную стоимость.",
            },
            (
                "Авторская исследовательская комбинация двух формул. "
                "Суммарная стоимость, уровень и порядок исполнения "
                "проверяются движком. Запись не разрешает "
                "бесконечное усиление заклинаний."
            ),
            links=[ref(spells[i], "combines"), ref(spells[i + 1], "combines")],
        )
    for i, profession in enumerate(professions):
        for j, task in enumerate(["оценка", "ремонт", "планирование", "обучение"]):
            add(
                f"skill_{i}_{j}",
                f"{profession.capitalize()}: {task}",
                "skill",
                {
                    "ability": ["intelligence", "dexterity", "wisdom", "charisma"][j],
                    "use": f"{task.capitalize()} в ремесле: {profession}",
                    "limit": "Навык не выдаёт результат без времени, ресурсов и проверки.",
                },
                (
                    f"Прикладной навык «{task}» для профессии «{profession}». "
                    f"Помогает выбрать подход и оценить риск. Проверку, сложность и "
                    f"результат определяет движок; описание не добавляет скрытый "
                    f"бонус."
                ),
            )
    validate_bundle(records)
    (OUT / "seed-v1.jsonl").write_text("\n".join(dump(r) for r in records) + "\n", encoding="utf-8")
    report = {
        "generator": "world-library-4",
        "records": len(records),
        "by_profile": dict(sorted(Counter(r["profile"] for r in records).items())),
        "sha256_canonical_records": digest(records),
        "human_reviewed": 0,
        "invented_homebrew": len(records),
        "note": (
            "Procedural regional/craft variants with bounded versioned handlers; "
            "not independently curated entities or a complete SRD implementation."
        ),
    }
    (OUT / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(dump(report))


if __name__ == "__main__":
    build()
