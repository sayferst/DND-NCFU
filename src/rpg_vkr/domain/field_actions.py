"""Finite emergency actions for revision three, used by the same battle scheduler."""


def perform(e, command, args):
    if e.state.get("catalog_revision") != 3:
        raise ValueError("Действие недоступно по правилам этой кампании.")
    if command == "flee":
        destination = args["destination"]
        if not e.state["battle"]:
            raise ValueError("Нет активной схватки.")
        if destination not in e.neighbors():
            raise ValueError("Нужен соседний известный путь.")
        if (
            e.state["living_world"].get("blocked_until", {}).get(e.scene.current, 0)
            > e.state["minute"]
        ):
            raise ValueError("Путь временно перекрыт.")
        if e.state["living_world"].get("blocked_until", {}).get(destination, 0) > e.state["minute"]:
            raise ValueError("Путь временно перекрыт.")
        if e.state["st"] < 3:
            raise ValueError("Недостаточно ST для отступления.")
        e.state["st"] -= 3
        if e.check("acrobatics", 12):
            e.state["last_battle"] = e.state["battle"]
            e.state.update(battle=None, active=None)
            e.travel(destination)
            e.events.append({"kind": "hero_retreat", "destination": destination})
            e.text.append("Герой отступил по соседнему пути; противники остались в мире.")
        else:
            e.text.append("Отступить пока не удалось.")
        return
    target = args["target"]
    actor, spec = e.actor(target, alive=False)
    if e.refs[target].place != e.scene.current or (actor.state or {}).get("life") == "dead":
        raise ValueError("Помощь этой цели недоступна.")
    if e.hp(target) != 0:
        raise ValueError("Первая помощь нужна потерявшему сознание.")
    item = e.owned(args["item"])
    row = e.template(item)
    if not (row.get("category") == "dressings" or row["id"] == "mat_3_0"):
        raise ValueError("Нужен бинт или чистая ткань.")
    e.consume_item(item)
    if e.check("medicine", 10):
        if e.state.get("owner_rules_policy") == 1:
            from rpg_vkr.domain.owner_rules import stabilize
            from rpg_vkr.domain.owner_rules_runtime import apply, life

            apply(e, target, stabilize(life(e, target)))
            e.text.append("Первая помощь стабилизировала цель при0HP без восстановления здоровья.")
        else:
            e.change_hp(target, 1)
        e.events.append({"kind": "first_aid", "actor": target})
        if e.state.get("owner_rules_policy") != 1:
            e.text.append("Первая помощь вернула сознание. Смерть она не отменяет.")
    else:
        e.text.append("Первая помощь не удалась; перевязочный материал израсходован.")
