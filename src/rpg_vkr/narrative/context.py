"""A player-visible, bounded snapshot for prose; secret state is never sent to a model."""

import hashlib
import json
from dataclasses import dataclass

from rpg_vkr.domain.character import ABILITY_NAMES
from rpg_vkr.domain.combat import ACTORS, ActorState, disposition_label, health_description
from rpg_vkr.domain.progression import ARCHETYPES
from rpg_vkr.domain.world import LOCATIONS, inventory_text, quest_text
from rpg_vkr.narrative.presentation import present_turn
from rpg_vkr.narrative.scenes import describe_scene

FIELD_LABELS = {
    "world.hp": "Здоровье героя",
    "world.max_hp": "Максимум здоровья героя",
    "world.gold": "Золото героя",
    "world.bandages": "Бинты героя",
    "world.basket": "Корзина поручения",
    "world.quest": "Поручение",
    "world.location": "Место",
    "world.explored": "Участок дороги исследован",
    "world.market_known": "Дорога на рынок известна",
    "world.trading": "Контакт с торговцем",
    "progress.xp": "Опыт героя",
    "progress.level": "Уровень героя",
    "hero.name": "Имя героя",
    "combat.surprise": "Незамеченный подход",
}
VALUE_LABELS = {
    "available": "не принято",
    "active": "принято",
    "completed": "завершено",
    "neutral": "нейтральное",
    "hostile": "враждебное",
}


def visible_changes(event):
    result = []
    for change in event.changes:
        key = change.field
        before, after = change.before, change.after
        if key.startswith("actor."):
            _, actor_id, field = key.split(".")
            if ACTORS[actor_id][1] != event.location:
                continue
            name = ACTORS[actor_id][0]
            if field == "hp":
                before = health_description(ActorState(actor_id, before, "neutral"))
                after = health_description(ActorState(actor_id, after, "neutral"))
                if before == after:
                    continue
                label = "Ранения: " + name
            else:
                label = "Отношение: " + name
        elif key.startswith("hero.") and key[5:] in ABILITY_NAMES:
            label = ABILITY_NAMES[key[5:]]
        elif key.startswith("training."):
            label = "Обучение: " + ABILITY_NAMES[key[9:]]
        elif key in FIELD_LABELS:
            label = FIELD_LABELS[key]
        else:
            # Never reveal NPC money/stock, exact HP, round counters or opaque state.
            continue

        def readable(value):
            if type(value) is bool:
                return "да" if value else "нет"
            return LOCATIONS.get(value, VALUE_LABELS.get(value, str(value)))

        result.append(f"{label}: {readable(before)} → {readable(after)}")
    return tuple(result)


@dataclass(frozen=True)
class NarrativeFrame:
    turn_index: int
    hero: str
    location: str
    scene: str
    health: str
    inventory: str
    quest: str
    visible_actors: tuple[str, ...]
    confirmed_result: str
    memories: tuple[str, ...]

    def to_dict(self):
        from dataclasses import asdict

        return asdict(self)

    @property
    def fingerprint(self):
        raw = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()


def build_frame(session):
    world = session.world
    hero = (
        f"{session.character.name}, {ARCHETYPES[session.progress.class_id].name}, "
        f"уровень {session.progress.level}, опыт {session.progress.xp}"
        if session.progress.enabled
        else f"{session.character.name}, учебная песочница без развития"
    )
    actors = tuple(
        (
            f"{ACTORS[a.id][0]}: погиб"
            if session.legacy_catalog_actor(a.id).state.get("life") == "dead"
            else f"{ACTORS[a.id][0]}: {disposition_label(a).lower()}, {health_description(a)}"
        )
        for a in session.combat.actors
        if session.actor_is_here(a.id)
    )
    if session.interactive_world:
        actor_states = (
            {e.id: e.state or {} for e in session.catalog.entities} if session.catalog else {}
        )
        actors += tuple(
            f"{a.name}: "
            + (
                "погиб"
                if actor_states.get(a.id, {}).get("life") == "dead"
                else "повержен"
                if actor_states.get(a.id, {}).get("hp") == 0
                else "рядом"
            )
            for a in session.interactive_world.actor_refs
            if a.id not in ACTORS and a.place == session.current_place_id
        )
    memories = []
    remembered_place = session.chronicle.seed.scene.place().name if session.generated_world else ""
    for event in session.memory.events:
        if session.generated_world:
            turn = session.turns[event.turn_index - 1]
            record = turn.interaction or turn.trade
            if record:
                remembered_place = record.after.place().name
            elif getattr(turn.catalog, "before", None):
                remembered_place = turn.catalog.before.place().name
        changes = visible_changes(event)
        if changes:
            # Use facts, not the untrusted player input or previous model's prose.
            memories.append(
                f"Событие {event.turn_index}, "
                + (remembered_place if session.generated_world else LOCATIONS[event.location])
                + ": "
                + "; ".join(changes)
            )
    items = inventory_text(world)
    if session.extra_items:
        items += "; " + "; ".join(name for name, _ in session.extra_items)
    if session.generated_world:
        items = session.interaction_state().inventory()
    confirmed = present_turn(session.turns[-1]).story if session.turns else session.introduction
    scene = describe_scene(world)
    if session.interactive_world:
        state = session.interactive_world
        place = state.place()
        scene = place.description or (
            describe_scene(world)
            if place.id in LOCATIONS and not session.generated_world
            else place.name
        )
        visible = [t for t in state.things if state.here(t) and state.root_holder(t) != "hero"]
        scene += "\nПредметы в этом месте: " + (
            "; ".join(f"{t.name} ×{t.quantity}" for t in visible)
            or "нет зарегистрированных предметов"
        )
        scene += "\nПри вас: " + state.inventory() + "."
    return NarrativeFrame(
        len(session.turns),
        hero,
        session.current_place_name,
        scene,
        f"{world.hp}/{world.max_hp}",
        items,
        ("Зацепки: " + "; ".join(session.chronicle.seed.hooks))
        if session.generated_world
        else (
            "Новое поручение недоступно: жительница повержена или враждебна."
            if world.quest == "available"
            and (
                session.combat.actor("villager").hp == 0
                or session.combat.actor("villager").disposition == "hostile"
            )
            else quest_text(world)
        ),
        actors,
        confirmed[:1500],
        tuple(text[:300] for text in memories[-6:]),
    )


def recent_dialogue(session):
    """Player words and authoritative outcomes; model prose never becomes a fact."""
    return tuple(
        {
            "player_message": turn.action[:200],
            "confirmed_result": present_turn(turn).story[:350],
            "source": turn.scene.version if turn.scene else "rules",
            "actor_id": turn.actor_id or "",
        }
        for turn in session.turns[-3:]
    )
