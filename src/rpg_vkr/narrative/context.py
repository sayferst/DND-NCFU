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
        f"{ACTORS[a.id][0]}: {disposition_label(a).lower()}, {health_description(a)}"
        for a in session.combat.actors
        if ACTORS[a.id][1] == world.location
    )
    memories = []
    for event in session.memory.events:
        changes = visible_changes(event)
        if changes:
            # Use facts, not the untrusted player input or previous model's prose.
            memories.append(
                f"Событие {event.turn_index}, {LOCATIONS[event.location]}: " + "; ".join(changes)
            )
    items = inventory_text(world)
    if session.extra_items:
        items += "; " + "; ".join(name for name, _ in session.extra_items)
    confirmed = present_turn(session.turns[-1]).story if session.turns else session.introduction
    return NarrativeFrame(
        len(session.turns),
        hero,
        LOCATIONS[world.location],
        describe_scene(world),
        f"{world.hp}/{world.max_hp}",
        items,
        (
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
        }
        for turn in session.turns[-3:]
    )
