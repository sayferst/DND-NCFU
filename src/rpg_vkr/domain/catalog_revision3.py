"""Revision three: class identities and finite ability/crafting prerequisites."""

from copy import deepcopy

FAMILIES = {
    "warrior": (
        ("Рубящий удар", "damage bleed"),
        ("Подсечка", "damage slow"),
        ("Удар эфесом", "damage stagger"),
        ("Разоружающий выпад", "damage disarm"),
        ("Стойка щита", "shield anchor"),
        ("Глухая защита", "defence ranged_guard"),
        ("Сосредоточенный натиск", "accuracy clarity"),
        ("Защита фланга", "resist defence"),
        ("Второе дыхание", "heal restore_st"),
        ("Передышка", "restore_st cure_bleed"),
        ("Полевая перевязка", "cure_bleed heal"),
        ("Боевой запал", "regenerate accuracy"),
        ("Воинский клич", "power anchor"),
        ("Сокрушающая серия", "damage weaken"),
        ("Осторожный шаг", "conceal haste"),
        ("Организованный отход", "travel conceal"),
    ),
    "archer": (
        ("Прицельная стрела", "damage mark"),
        ("Стрела в ногу", "damage slow"),
        ("Оглушающий выстрел", "damage stagger"),
        ("Сбивающий выстрел", "damage disarm"),
        ("Выверенный прицел", "accuracy perception"),
        ("Дальнее наблюдение", "perception light"),
        ("Стрелковая позиция", "defence ranged_guard"),
        ("Смена позиции", "haste conceal"),
        ("Короткая передышка", "restore_st clarity"),
        ("Походная помощь", "heal cure_bleed"),
        ("Изучение следов", "reveal_actors perception"),
        ("Разведка троп", "reveal_routes conceal"),
        ("Залп по уязвимому месту", "damage weaken"),
        ("Оценка добычи", "appraise perception"),
        ("Поиск припасов", "reveal_items perception"),
        ("Отступление стрелка", "travel haste"),
    ),
    "rogue": (
        ("Удар исподтишка", "damage bleed"),
        ("Подрезание сухожилий", "damage slow"),
        ("Сбивающий удар", "damage stagger"),
        ("Ловкое разоружение", "damage disarm"),
        ("Скользящая защита", "defence haste"),
        ("Незаметный силуэт", "conceal perception"),
        ("Точный выпад", "accuracy power"),
        ("Холодный расчёт", "clarity anchor"),
        ("Перехват дыхания", "restore_st cure_weaken"),
        ("Первая помощь", "heal cure_bleed"),
        ("Разведка карманов", "reveal_items conceal"),
        ("Чтение обстановки", "reveal_actors perception"),
        ("Незаметный проход", "reveal_routes conceal"),
        ("Обнаружение тайников", "reveal_nodes perception"),
        ("Выход из захвата", "dispel haste"),
        ("Путь к отступлению", "travel conceal"),
    ),
    "mage": (
        ("Пламенный импульс", "damage burn"),
        ("Ледяные оковы", "damage slow"),
        ("Громовой толчок", "damage stagger"),
        ("Ослабляющее проклятие", "damage weaken"),
        ("Чародейский заслон", "shield anchor"),
        ("Защитная формула", "defence resist"),
        ("Зеркальная печать", "reflect ranged_guard"),
        ("Арканная концентрация", "accuracy clarity"),
        ("Перестройка потока", "restore_mp clarity"),
        ("Магическое восстановление", "heal cure_burn"),
        ("Восстановление сознания", "revive regenerate"),
        ("Поддержка дыхания", "restore_st haste"),
        ("Магический свет", "light reveal_items"),
        ("Обнаружение жизни", "reveal_actors perception"),
        ("Разрыв чар", "dispel anchor"),
        ("Пространственный шаг", "travel conceal"),
    ),
    "cleric": (
        ("Луч праведности", "damage mark"),
        ("Сдерживающая молитва", "damage slow"),
        ("Слово отторжения", "damage stagger"),
        ("Ослабление скверны", "damage weaken"),
        ("Заступничество", "shield anchor"),
        ("Благословенная защита", "defence resist"),
        ("Защитная аура", "ranged_guard reflect"),
        ("Благословение стойкости", "clarity power"),
        ("Живительная молитва", "heal cure_bleed"),
        ("Очищение огня", "cure_burn heal"),
        ("Очищение яда", "cure_poison regenerate"),
        ("Возвращение сознания", "revive restore_st"),
        ("Ободрение", "restore_st anchor"),
        ("Свет надежды", "light perception"),
        ("Очищение чар", "dispel cure_weaken"),
        ("Путь паломника", "reveal_routes haste"),
    ),
    "artisan": (
        ("Удар рабочим молотом", "damage stagger"),
        ("Сковывающий приём", "damage slow"),
        ("Удар по креплению", "damage weaken"),
        ("Точный инструмент", "accuracy power"),
        ("Быстрый ремонт", "repair craft"),
        ("Осмотр снаряжения", "appraise perception"),
        ("Рабочая сосредоточенность", "craft clarity"),
        ("Защитная стойка", "defence anchor"),
        ("Полевой уход", "heal cure_bleed"),
        ("Рабочая передышка", "restore_st cure_weaken"),
        ("Определение залежей", "reveal_nodes perception"),
        ("Поиск материалов", "reveal_items perception"),
        ("Оценка местности", "reveal_routes perception"),
        ("Укреплённое снаряжение", "shield resist"),
        ("Безопасный демонтаж", "dispel craft"),
        ("Сбор походного лагеря", "regenerate conceal"),
    ),
}


def build(previous):
    data = deepcopy(previous)
    data["revision"] = 3
    grouped = {k: [] for k in FAMILIES}
    for r in data["records"]:
        if r["kind"] in ("weapon", "armour", "household"):
            r["durability"] = (
                50 if r["kind"] == "weapon" else 60 if r["kind"] == "armour" else 40
            ) + 3 * r["level"]
        if r["kind"] == "recipe" and r["category"] == "repair":
            r["repair_power"] = 12 + 2 * r["level"]
        if r["kind"] == "talent":
            grouped[r["class_id"]].append(r)
        if r["kind"] == "consumable" and r["category"] == "ammunition":
            r["batch"] = 12
            r["price_cp"] = 2 + r.get("level", 1) // 3
    for class_id, rows in grouped.items():
        for index, r in enumerate(rows):
            title, operations = FAMILIES[class_id][index // 5]
            r["name"] = title + " — " + r["name"].split(" — ")[-1]
            r["description"] = (
                title
                + ". "
                + (
                    "Расходует реальные боеприпасы. "
                    if class_id == "archer" and "damage" in operations
                    else ""
                )
                + "Требования, затраты и восстановление проверяются движком."
            )
            r["effects"] = [{"op": op, "power": 1 + index // 40} for op in operations.split()]
            r["dice"] = f"{1 + r['level'] // 8}d" + ("8" if "damage" in operations else "6")
            r["element"] = (
                "radiant"
                if class_id == "cleric"
                else ("fire", "cold", "lightning", "shadow")[index // 5 % 4]
                if class_id == "mage"
                else "physical"
            )
            r["requires_ammunition"] = class_id == "archer" and "damage" in operations.split()
            r["requires_repair_material"] = class_id == "artisan" and "repair" in operations.split()
            if class_id in ("mage", "cleric"):
                r["mp"] = 2 + index // 20
            if "heal" in operations or "regenerate" in operations:
                r["cooldown"] = max(r["cooldown"], 6)
    return data


def pay_ability_materials(e, row, selected):
    if row.get("requires_ammunition"):
        arrows = [i for i in e.state["items"] if i["owner"] == "hero" and i.get("ammunition")]
        usable = []
        for item in arrows:
            try:
                e.owned(item["id"])
            except ValueError:
                continue
            usable.append(item)
        if sum(i["quantity"] for i in usable) < len(selected):
            raise ValueError("Недостаточно боеприпасов для способности.")
        remaining = len(selected)
        for item in usable:
            n = min(remaining, item["quantity"])
            e.consume_item(item, n)
            remaining -= n
            if not remaining:
                break
    if row.get("requires_repair_material"):
        item = e.owned(selected[0])
        template = e.template(item)
        material = template.get("material", "mat_0_0")
        base = int(material.split("_")[1])
        for ingredient, n in e.require_materials({f"mat_{base}_0": 1}):
            e.consume_item(ingredient, n)
