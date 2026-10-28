"""Session state and command routing; narration never performs dice calculations."""

from dataclasses import asdict, dataclass, replace

from rpg_vkr.commands import CHAT_TARGETS, NPC_CONTACTS, allowed_intents, normalise_action
from rpg_vkr.domain.adventure import Chronicle, MemoryNote, WorldSeed, input_signature
from rpg_vkr.domain.campaign import Campaign, NPCProfile, procedural_profile
from rpg_vkr.domain.catalog import (
    Catalog,
    Registration,
    register,
    seed_catalog,
    validate_plan_properties,
)
from rpg_vkr.domain.catalog_actions import ActorAttempt, resolve_attempt, restore_attempt
from rpg_vkr.domain.challenge import CHALLENGES, Challenge, needs_model_review, proposed_challenge
from rpg_vkr.domain.character import (
    ABILITY_NAMES,
    AbilityCheck,
    Character,
    describe_check,
    resolve_ability_check,
)
from rpg_vkr.domain.combat import (
    ACTORS,
    COMBAT_COMMANDS,
    NAMES_TO_IDS,
    CombatState,
    disposition_label,
    health_description,
    perform_combat,
)
from rpg_vkr.domain.combat_record import CombatRecord, canonical, restore_record
from rpg_vkr.domain.dice import D20Roll, DiceRoller
from rpg_vkr.domain.director import SceneRecord, validate_scene
from rpg_vkr.domain.inspection import COMMAND as INSPECT_COMMAND
from rpg_vkr.domain.inspection import Inspection, inspect, requested_abilities
from rpg_vkr.domain.interactions import (
    Interaction,
    InteractiveWorld,
    WorldPlan,
    apply_plan,
    bind_plan,
)
from rpg_vkr.domain.meaning import Meaning
from rpg_vkr.domain.memory import WorldMemory, snapshot
from rpg_vkr.domain.progression import (
    ARCHETYPES,
    PRACTICE_COMMANDS,
    HeroProgress,
    describe_award,
    describe_progress,
)
from rpg_vkr.domain.resources import activate as activate_resources
from rpg_vkr.domain.resources import needed as resource_plan
from rpg_vkr.domain.resources import physical, project, reconcile, validate_balances
from rpg_vkr.domain.social import DialogueRecord, grievance
from rpg_vkr.domain.trade import TradeRecord, restore_trade, transact
from rpg_vkr.domain.world import (
    LOCATIONS,
    OBSERVE_COMMANDS,
    WHERE_COMMANDS,
    WORLD_COMMANDS,
    WorldState,
    perform_action,
)
from rpg_vkr.gameplay_session import atomic
from rpg_vkr.narrative.dialogue import dialogue_intent, last_interlocutor, resolve_conversation
from rpg_vkr.narrative.offline import INTRODUCTION, respond
from rpg_vkr.narrative.records import Narration
from rpg_vkr.narrative.scenes import describe_scene
from rpg_vkr.narrative.speech import command_target, validate_binding

ROLL_COMMANDS = {"бросить d20", "бросить д20", "бросить кубик"}
CHECK_COMMANDS = {
    "проверить силу": "strength",
    "проверить ловкость": "dexterity",
    "проверить телосложение": "constitution",
    "проверить интеллект": "intelligence",
    "проверить мудрость": "wisdom",
    "проверить харизму": "charisma",
}
NPC_SPEAKERS = {"Стражник", "Жительница", "Торговец"}
MAX_TURNS = 2000


@dataclass(frozen=True)
class Turn:
    action: str
    speaker: str
    text: str
    roll: D20Roll | None = None
    check: AbilityCheck | None = None
    actor_id: str | None = None
    combat: CombatRecord | None = None
    intent: str | None = None
    origin: str = "typed"
    dialogue: DialogueRecord | None = None
    meaning: Meaning | None = None
    player_name: str | None = None
    inspection: Inspection | None = None
    intent_source: str = "direct"
    scene: SceneRecord | None = None
    notes: tuple[str, ...] = ()
    challenge: Challenge | None = None
    interaction: Interaction | None = None
    catalog: Registration | ActorAttempt | None = None
    trade: TradeRecord | None = None
    gameplay: dict | None = None


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("Invalid session text")
    return value


class Session:
    @property
    def history_limit(self):
        return MAX_TURNS

    def __init__(
        self,
        seed: int | None = None,
        character: Character | None = None,
        world: WorldState | None = None,
        progress: HeroProgress | None = None,
        combat: CombatState | None = None,
        campaign: Campaign | None = None,
    ) -> None:
        self.campaign = Campaign.create() if campaign is None else campaign
        self.dice = DiceRoller(seed)
        self.character = Character() if character is None else character
        self.world = WorldState() if world is None else world
        self.progress = HeroProgress() if progress is None else progress
        if self.progress.enabled and self.progress.character() != self.character:
            raise ValueError("Character does not match development history")
        self.combat = CombatState() if combat is None else combat
        self.introduction = INTRODUCTION
        self._turns: list[Turn] = []
        self.memory = WorldMemory(
            0, snapshot(self.world, self.character, self.combat, self.progress)
        )
        self._narrations: list[Narration] = []
        self.interactive_world: InteractiveWorld | None = None
        self.catalog: Catalog | None = None
        self.chronicle: Chronicle | None = None
        self._d20_progress = None
        self._gameplay = None

    @property
    def d20_progress(self):
        from rpg_vkr.domain.campaign_progress import synchronized

        return synchronized(self._d20_progress, self.turns)

    @property
    def schema_version(self):
        if hasattr(self, "_fork"):
            return 29
        if self._gameplay is not None:
            from rpg_vkr.domain.gameplay_rules import revision

            return 23 + revision(self._gameplay["state"])
        return 23 if self._d20_progress is not None else 22

    @property
    def gameplay(self):
        from copy import deepcopy

        return deepcopy(self._gameplay["state"]) if self._gameplay else None

    @property
    def in_combat(self):
        return bool(self.combat.active or self._gameplay and self._gameplay["state"]["active"])

    @property
    def effective_character(self):
        if self._gameplay:
            from rpg_vkr.domain.gameplay import effective_character

            character = self.character
            if self.schema_version >= 28:
                from rpg_vkr.domain.content_v5 import inherited

                character = inherited(character, self._gameplay["state"])
            return effective_character(self._gameplay["state"], character)
        return self.character

    def _request_token(self):
        import uuid

        fork = getattr(self, "_fork", None)
        if fork:
            index = getattr(self, "_fork_replay_index", len(fork["operations"]))
            return uuid.uuid5(
                uuid.UUID(fork["world_id"]), f"operation:{index}:turn:{len(self.turns)}"
            ).hex
        return uuid.uuid4().hex

    def enable_gameplay(self, identity, *, revision=1):
        from rpg_vkr.gameplay_session import enable

        enable(self, identity, revision=revision)

    def _finish_turn(self, turn):
        from rpg_vkr.gameplay_session import finish_turn

        return finish_turn(self, turn)

    def perform_gameplay(self, command, args, request_id, *, action=None):
        from rpg_vkr.gameplay_session import perform

        return perform(self, command, args, request_id, action=action)

    def preview_gameplay(self, command, args):
        from rpg_vkr.domain.gameplay_rules import execute
        from rpg_vkr.gameplay_session import context

        if self._gameplay is None:
            raise ValueError("Новый набор правил не включён.")
        preview_dice = DiceRoller(self.dice.seed)
        preview_dice.restore(self.dice.checkpoint())
        return execute(self._gameplay["state"], command, args, context(self), preview_dice)

    def enable_d20_progress(self):
        from rpg_vkr.domain.d20_progression import D20Progress

        if self.turns or self._d20_progress is not None or not self.progress.enabled:
            raise ValueError("Новые навыки выбираются при создании героя.")
        self._d20_progress = D20Progress()

    def train_skill(self, skill):
        progress = self.d20_progress
        if progress is None or self.in_combat or self.world.hp <= 0:
            raise ValueError("Обучение сейчас недоступно.")
        self._d20_progress = progress.train(skill, f"training:{len(progress.events)}")

    def commit_skill_allocation(self, increments, command_id, expected):
        from rpg_vkr.domain.skill_allocation import commit

        progress = self.d20_progress
        if progress is None or self.in_combat or self.world.hp <= 0:
            raise ValueError("Обучение сейчас недоступно.")
        self._d20_progress = commit(progress, increments, command_id, expected)

    @property
    def generated_world(self):
        return bool(self.chronicle and self.chronicle.seed)

    def start_world(self, seed):
        if self.turns or not self.progress.enabled or self.generated_world:
            raise ValueError("Новый мир создаётся при рождении нового героя.")
        if not isinstance(seed, WorldSeed) or seed.signature != input_signature(
            self.campaign, self.progress.class_id
        ):
            raise ValueError("Этот мир создан для другого героя.")
        candidate_gameplay = None
        if self.schema_version >= 26:
            from rpg_vkr.domain.factions import initialize

            candidate_gameplay = initialize(self._gameplay["state"], seed.catalog, seed.scene)
        if self._gameplay:
            from rpg_vkr.domain.gameplay import ensure_names

            ensure_names(candidate_gameplay or self._gameplay["state"], seed.catalog)
        world = project(seed.scene, replace(self.world, quest="completed", basket=0, trading=False))
        if candidate_gameplay is not None:
            self._gameplay["state"] = candidate_gameplay
        self.chronicle = Chronicle(seed)
        self.catalog, self.interactive_world = seed.catalog, seed.scene
        self.world, self.introduction = world, seed.opening
        self.memory = WorldMemory(0, snapshot(world, self.character, self.combat, self.progress))

    def write_diary(self, title, text, *, id=None, pinned=False, delete=False, place=None):
        if hasattr(self, "_fork") and id is None:
            import uuid

            from rpg_vkr.domain.adventure import DiaryRevision

            id = str(uuid.UUID(self._request_token()))
            chronicle = self.chronicle or Chronicle()
            entry = DiaryRevision(
                id,
                title,
                text,
                self.current_place_name if place is None else place,
                len(self.turns),
                pinned,
                delete,
            )
            self.chronicle = replace(chronicle, diary=chronicle.diary + (entry,))
            return
        self.chronicle = (self.chronicle or Chronicle()).revise(
            title,
            text,
            self.current_place_name if place is None else place,
            len(self.turns),
            id=id,
            pinned=pinned,
            delete=delete,
        )

    def remember(self, values, source):
        self.chronicle = self.checked_memories(values, source)

    def checked_memories(self, values, source, *, scene=None, turn=None):
        if len(values) > 8:
            raise ValueError("Слишком много новых воспоминаний за один ход.")
        scene = scene or self.interaction_state()
        subjects = {
            "world",
            "hero",
            "plot",
            *[p.id for p in scene.places],
            *[a.id for a in scene.actor_refs],
            *[t.id for t in scene.things],
        }
        notes = tuple(
            MemoryNote(
                **(value | {"turn": len(self.turns) if turn is None else turn, "source": source})
            )
            for value in values
        )
        if any(n.subject not in subjects for n in notes):
            raise ValueError("Воспоминание относится к неизвестному объекту.")
        if self.catalog:
            for note in notes:
                if note.kind != "appearance":
                    continue
                entity = next((e for e in self.catalog.entities if e.id == note.subject), None)
                definition = next(
                    (
                        d
                        for d in self.catalog.definitions
                        if entity and d.id == entity.definition_id
                    ),
                    None,
                )
                appearance = definition.properties.get("appearance") if definition else None
                if appearance and note.text != appearance:
                    raise ValueError(
                        "Внешность уже определена каталогом; используйте установленный текст."
                    )
        return (self.chronicle or Chronicle()).remember(notes)

    @classmethod
    def create_hero(
        cls,
        character: Character,
        class_id: str,
        seed: int | None = None,
        *,
        description="",
        world_brief="",
    ):
        progress = HeroProgress(class_id, character)
        kit = ARCHETYPES[class_id]
        return cls(
            seed=seed,
            character=character,
            world=WorldState(gold=kit.gold, bandages=kit.bandages),
            progress=progress,
            campaign=Campaign.create(description, world_brief),
        )

    @property
    def extra_items(self) -> tuple[tuple[str, str], ...]:
        if self._gameplay:
            from rpg_vkr.domain.gameplay_v2 import name

            return tuple(
                (name(i), f"{i['id']}; состояние {i['durability']}/20")
                for i in self._gameplay["state"]["items"]
                if i["owner"] == "hero"
            )
        kit = ARCHETYPES[self.progress.class_id] if self.progress.enabled else None
        base = (
            (
                (kit.equipment, "Оружие для авторской схватки"),
                ("Дорожный учебник", "Изучить один раз для обучения Интеллекту"),
            )
            if kit
            else ()
        )
        return base + tuple(
            (f"{t.name} ×{t.quantity}", "Переносимый предмет мира")
            for t in (self.interactive_world.carried() if self.interactive_world else ())
            if not t.resource
        )

    @property
    def current_place_id(self):
        return self.interactive_world.current if self.interactive_world else self.world.location

    @property
    def current_place_name(self):
        return (
            self.interactive_world.place().name
            if self.interactive_world
            else LOCATIONS[self.world.location]
        )

    @property
    def visited_places(self):
        result = {self.chronicle.seed.scene.current} if self.generated_world else {"gate"}
        for turn in self.turns:
            if turn.interaction:
                result.update((turn.interaction.before.current, turn.interaction.after.current))
        result.add(self.current_place_id)
        return result

    @property
    def extra_inventory_rows(self):
        if self._gameplay:
            return tuple((name, 1, detail) for name, detail in self.extra_items) + tuple(
                (t.name, t.quantity, "Переносимый предмет мира")
                for t in (self.interactive_world.carried() if self.interactive_world else ())
                if not t.resource
            )
        base = self.extra_items[:2] if self.progress.enabled else ()
        return tuple((name, 1, purpose) for name, purpose in base) + tuple(
            (t.name, t.quantity, "Переносимый предмет мира")
            for t in (self.interactive_world.carried() if self.interactive_world else ())
            if not t.resource
        )

    def actor_is_here(self, actor_id):
        if not any(
            a.id == actor_id and a.place == self.current_place_id
            for a in self.interaction_state().actor_refs
        ):
            return False
        if self._gameplay:
            from rpg_vkr.domain.gameplay import available

            if self._gameplay["state"]["active"] == actor_id:
                return True
            battle = self._gameplay["state"].get("battle")
            if battle and actor_id in battle["order"]:
                return True  # A defeated participant's body is still physically present.
            entity = (
                next((e for e in self.catalog.entities if e.id == actor_id), None)
                if self.catalog
                else None
            )
            definition = (
                next(
                    (
                        d
                        for d in self.catalog.definitions
                        if entity and d.id == entity.definition_id
                    ),
                    None,
                )
                if self.catalog
                else None
            )
            return available(self._gameplay["state"], actor_id, definition)
        return True

    def interaction_state(self):
        return self.interactive_world or InteractiveWorld.initial(self.world.location)

    def plan_state(self, plan):
        scene = self.interaction_state()
        if resource_plan(scene, plan, self.catalog, self.catalog_aliases):
            return activate_resources(scene, self.world, self.catalog, self.catalog_aliases)
        return scene

    @property
    def catalog_aliases(self):
        from rpg_vkr.domain.gameplay_v2 import aliases

        return aliases(self.turns)

    @atomic
    def submit_trade(self, action, merchant_id, item_id, operation, quantity, source="player-ui"):
        action = _text(action, 500)
        if self.schema_version >= 25:
            if any(i["id"] == item_id for i in self._gameplay["state"]["items"]):
                if quantity != 1:
                    raise ValueError("Экземпляр снаряжения продаётся по одному.")
                return self.perform_gameplay(
                    operation,
                    {"merchant": merchant_id, "item": item_id},
                    "trade_" + self._request_token(),
                    action=action,
                )
            return self.perform_gameplay(
                "trade_world",
                {
                    "merchant": merchant_id,
                    "item": item_id,
                    "operation": operation,
                    "quantity": quantity,
                },
                "trade_" + self._request_token(),
                action=action,
            )
        if (
            not self.catalog
            or self.in_combat
            or self.world.hp <= 0
            or len(self.turns) >= self.history_limit
        ):
            raise ValueError("Сделка сейчас недоступна.")
        catalog, world, record = transact(
            self.catalog,
            self.interaction_state(),
            self.world,
            merchant_id,
            item_id,
            operation,
            quantity,
            len(self.turns) + 1,
            source,
            self.catalog_aliases,
        )
        turn = Turn(
            action,
            "Мир",
            record.summary,
            player_name=self.character.name,
            intent_source="model",
            trade=record,
        )
        memory = self.memory.append(
            turn,
            snapshot(self.world, self.character, self.combat, self.progress),
            snapshot(world, self.character, self.combat, self.progress),
        )
        self.catalog, self.world, self.interactive_world, self.memory = (
            catalog,
            world,
            record.after,
            memory,
        )
        self._turns.append(turn)
        return self._finish_turn(turn)

    @atomic
    def register_catalog(self, action, definitions, entities, reason, model):
        action = _text(action, 500).strip()
        if self.in_combat or self.world.hp <= 0 or len(self.turns) >= self.history_limit:
            raise ValueError("Создание сцены недоступно в схватке или после выбытия.")
        record = Registration(
            tuple(definitions),
            tuple(entities),
            reason,
            model,
            len(self.turns),
            self.interaction_state(),
        )
        catalog, expanded = register(self.catalog or seed_catalog(), record.before, record)
        if self._gameplay:
            from rpg_vkr.domain.gameplay import ensure_names

            ensure_names(self._gameplay["state"], catalog)
        names = {d.id: d.name for d in catalog.definitions}
        text = (
            "Вы замечаете: " + "; ".join(names[e.definition_id] for e in entities) + "."
            if entities
            else "Сохранены сведения: " + "; ".join(d.name for d in definitions) + "."
        )
        turn = Turn(
            action,
            "Мир",
            text,
            player_name=self.character.name,
            intent_source="model",
            catalog=record,
        )
        before = snapshot(self.world, self.character, self.combat, self.progress)
        memory = self.memory.append(turn, before, before)
        self.catalog, self.interactive_world, self.memory = catalog, expanded, memory
        self._turns.append(turn)
        return self._finish_turn(turn)

    def legacy_catalog_actor(self, target_id):
        from rpg_vkr.domain.catalog import Entity

        if target_id not in ACTORS:
            return None
        actor = self.combat.actor(target_id)
        state = {"hp": actor.hp, "disposition": actor.disposition}
        last = next(
            (
                t.catalog
                for t in reversed(self.turns)
                if isinstance(t.catalog, ActorAttempt) and t.catalog.target_id == target_id
            ),
            None,
        )
        if last and last.entity_after.state.get("life") == "dead" and actor.hp == 0:
            state["life"] = "dead"
        if actor.hp == 0 and self._gameplay:
            outcome = next(
                (
                    a
                    for t in reversed(self.turns)
                    if t.gameplay
                    for a in reversed(t.gameplay["result"]["attacks"])
                    if a["target_id"] == target_id and a["defeated"]
                ),
                None,
            )
            if outcome:
                state["life"] = "dead" if outcome["killed"] else "unconscious"
        return Entity(target_id, "type_actor_" + target_id, ACTORS[target_id][1], state=state)

    @atomic
    def submit_actor_attempt(
        self, action, target_id, operation, lethal, reason, model, *, confirmed_intent=False
    ):
        from rpg_vkr.domain.catalog_actions import bind_attempt

        action = _text(action, 500)
        bind_attempt(action, operation, lethal, confirmed=confirmed_intent)
        if self._gameplay is not None and operation == "attack":
            return self.perform_gameplay(
                "attack",
                {"target": target_id, "lethal": int(lethal)},
                "cmd_" + self._request_token(),
                action=action,
            )
        if self.in_combat or self.world.hp <= 0 or len(self.turns) >= self.history_limit:
            raise ValueError("Сначала завершите текущую схватку или загрузите живого героя.")
        catalog = self.catalog or seed_catalog()
        scene = self.interaction_state()
        kwargs = dict(
            catalog=catalog,
            scene=scene,
            world=self.world,
            character=self.character,
            target_id=target_id,
            operation=operation,
            lethal=lethal,
            reason=reason,
            model=model,
            base_turn=len(self.turns),
            legacy_entity=self.legacy_catalog_actor(target_id),
        )
        # Validate before consuming RNG or a bandage.
        resolve_attempt(**kwargs, roll=D20Roll(self.dice.checkpoint()[1] + 1, 10), preview=True)
        checkpoint = self.dice.checkpoint()
        try:
            roll = self.dice.roll_d20()
            catalog, world, record = resolve_attempt(**kwargs, roll=roll, preview=True)
            if (
                scene.version == "interactive-world-4"
                and operation == "attack"
                and record.entity_after.state["hp"] > 0
            ):
                catalog, world, record = resolve_attempt(
                    **kwargs, roll=roll, counter_roll=self.dice.roll_d20()
                )
            resource_scene = reconcile(scene, self.world, world, len(self.turns) + 1, catalog)
            combat = self.combat
            if target_id in ACTORS:
                actor = combat.actor(target_id)
                combat = combat.update(
                    replace(
                        actor,
                        hp=record.entity_after.state["hp"],
                        disposition=record.entity_after.state["disposition"],
                    )
                )
            turn = Turn(
                action,
                "Мир",
                record.summary,
                record.roll,
                record.check,
                player_name=self.character.name,
                intent_source="model",
                catalog=record,
            )
            memory = self.memory.append(
                turn,
                snapshot(self.world, self.character, self.combat, self.progress),
                snapshot(world, self.character, combat, self.progress),
            )
        except Exception:
            self.dice.restore(checkpoint)
            raise
        self.catalog, self.world, self.combat, self.memory = catalog, world, combat, memory
        if physical(scene):
            self.interactive_world = resource_scene
        self._turns.append(turn)
        return self._finish_turn(turn)

    @atomic
    def submit_interaction(self, action, plan, *, confirmed_plan=False, origin="typed"):
        action = _text(action, 500).strip()
        if origin not in {"typed", "system"}:
            raise ValueError("Неверный источник шага.")
        if not isinstance(plan, WorldPlan) or not plan.steps:
            raise ValueError("Нет плана изменения мира.")
        bind_plan(action, plan, confirmed=confirmed_plan)
        if self.in_combat or self.world.hp <= 0 or len(self.turns) >= self.history_limit:
            raise ValueError("Эта цепочка недоступна в бою или после выбытия.")
        before = self.plan_state(plan)
        index = len(self.turns) + 1
        if self.catalog or physical(before):
            validate_plan_properties(
                self.catalog or seed_catalog(),
                before,
                plan,
                turn_index=index,
                aliases=self.catalog_aliases,
            )
        _, risky, _, _ = apply_plan(before, plan, turn_index=index)
        checkpoint = self.dice.checkpoint()
        try:
            roll = self.dice.roll_d20() if risky else None
            check = (
                resolve_ability_check("dexterity", self.character.dexterity, roll.value, 15)
                if roll
                else None
            )
            if roll and getattr(self, "is_unified", False):
                from rpg_vkr.domain.character import AbilityCheck
                from rpg_vkr.domain.unified import bonus

                ability, modifier = bonus(self.gameplay, self.effective_character, "stealth")
                total = roll.value + modifier
                check = AbilityCheck(
                    ability, self.effective_character.dexterity, 15, modifier, total, total >= 15
                )
            after, _, witnesses, messages = apply_plan(
                before,
                plan,
                check_succeeded=check.succeeded if check else True,
                turn_index=index,
            )
            record = Interaction(
                before,
                plan,
                after,
                witnesses,
                "\n".join(messages),
                roll,
                check,
                "interaction-homebrew-2"
                if before.version == "interactive-world-4"
                else "interaction-homebrew-1",
            )
            catalog = self.catalog
            if catalog and before.version == "interactive-world-4":
                from rpg_vkr.domain.npc_reactions import react

                catalog = react(catalog, record, index)
            combat = replace(
                self.combat,
                actors=tuple(
                    replace(a, disposition="hostile") if a.id in witnesses and a.hp > 0 else a
                    for a in self.combat.actors
                ),
            )
            anchor = after.place().anchor
            world = replace(
                self.world,
                location=anchor,
                trading=False if after.current != before.current else self.world.trading,
                market_known=self.world.market_known or anchor == "market",
            )
            world = project(after, world)
            turn = Turn(
                action,
                "Мир",
                record.summary,
                roll,
                check,
                player_name=self.character.name,
                intent_source="model",
                interaction=record,
                origin=origin,
            )
            memory = self.memory.append(
                turn,
                snapshot(self.world, self.character, self.combat, self.progress),
                snapshot(world, self.character, combat, self.progress),
            )
        except Exception:
            self.dice.restore(checkpoint)
            raise
        self.world, self.combat, self.memory = world, combat, memory
        self.interactive_world = after
        self.catalog = catalog
        self._turns.append(turn)
        return self._finish_turn(turn)

    @atomic
    def submit_challenge(self, action: str, *, suggested_kind=None, assessment=None) -> Turn:
        action = _text(action, 500).strip()
        if assessment:
            from rpg_vkr.domain.challenge import validate_assessment

            validate_assessment(assessment)
            from rpg_vkr.domain.interactions import nonexecuting

            if nonexecuting(action):
                raise ValueError("Вопрос или отрицание не выполняют проверку.")
            kind = "general"
        else:
            kind = proposed_challenge(action)
            if suggested_kind is not None:
                from rpg_vkr.narrative.actions import action_plan

                if (
                    suggested_kind not in CHALLENGES
                    or (kind and suggested_kind != kind)
                    or (kind is None and not needs_model_review(action))
                    or action_plan(self, action) is not None
                ):
                    raise ValueError("Предложение проверки не соответствует попытке.")
                kind = suggested_kind
            if kind is None:
                raise ValueError("Для этой попытки пока нет проверяемой проверки.")
        if self.in_combat or self.world.hp <= 0 or len(self.turns) >= self.history_limit:
            raise ValueError("Эта проверка недоступна во время схватки или после выбытия.")
        ability, difficulty = (
            (assessment["ability"], assessment["dc"]) if assessment else CHALLENGES[kind][:2]
        )
        checkpoint = self.dice.checkpoint()
        try:
            roll = self.dice.roll_d20()
            from rpg_vkr.domain.challenge import CHALLENGE_SKILLS

            skill = CHALLENGE_SKILLS.get(kind)
            d20 = self.d20_progress
            if assessment and "skill" in assessment and d20 is None:
                raise ValueError("Навыки D20 не включены для этой кампании.")
            if assessment and d20 is not None:
                skill = assessment.get("skill") or {
                    "strength": "athletics",
                    "dexterity": "acrobatics",
                    "intelligence": "knowledge",
                    "wisdom": "perception",
                    "charisma": "persuasion",
                }.get(ability)
            spec = assessment
            check = resolve_ability_check(
                ability, self.effective_character.score(ability), roll.value, difficulty
            )
            record_version = "challenge-homebrew-2" if assessment else "challenge-homebrew-1"
            if d20 is not None and skill:
                rank = d20.rank(skill)
                bonus = 2 * rank
                spec = {
                    "ability": ability,
                    "dc": difficulty,
                    "purpose": assessment["purpose"] if assessment else CHALLENGES[kind][2],
                    "skill": skill,
                    "rank": rank,
                    "revision": len(d20.events),
                }
                check = replace(
                    check,
                    modifier=check.modifier + bonus,
                    total=check.total + bonus,
                    succeeded=check.total + bonus >= difficulty,
                )
                record_version = "challenge-homebrew-3"
            record = Challenge(
                kind,
                self.world.location,
                roll,
                check,
                version=record_version,
                assessment=spec,
            )
            turn = Turn(
                action,
                "Правила",
                record.story(),
                roll,
                record.check,
                player_name=self.character.name,
                intent_source="model" if suggested_kind is not None else "local-fallback",
                challenge=record,
            )
            state = snapshot(self.world, self.character, self.combat, self.progress)
            memory = self.memory.append(turn, state, state)
        except Exception:
            self.dice.restore(checkpoint)
            raise
        self._turns.append(turn)
        self.memory = memory
        return self._finish_turn(turn)

    @property
    def turns(self) -> tuple[Turn, ...]:
        return tuple(self._turns)

    @atomic
    def submit(
        self,
        action: str,
        *,
        intent: str | None = None,
        origin="typed",
        meaning=None,
        profile=None,
        intent_source="direct",
        _verified_step=False,
    ) -> Turn:
        action = _text(action, 500).strip()
        if self._gameplay is not None and intent is None and meaning is None:
            from rpg_vkr.domain.gameplay_commands import parse

            parsed = parse(action)
            if parsed:
                return self.perform_gameplay(
                    *parsed, "text_" + self._request_token(), action=action
                )
        if len(self._turns) >= self.history_limit:
            raise ValueError(f"Достигнут предел в {self.history_limit} действий. Сохраните сессию.")
        if intent is not None and (not isinstance(intent, str) or intent not in allowed_intents()):
            raise ValueError("Неподдерживаемое намерение. Мир не изменён.")
        if meaning is not None and not isinstance(meaning, Meaning):
            raise ValueError("Invalid semantic evidence")
        if meaning is None and intent is None and not _verified_step:
            from rpg_vkr.narrative.routing import infer_meaning

            meaning = infer_meaning(self, action)
        if meaning is not None:
            from rpg_vkr.narrative.routing import meaning_command

            expected = meaning_command(meaning)
            if intent is not None and intent != expected:
                raise ValueError("Meaning does not match executable command")
            intent = expected
        if intent is None:
            from rpg_vkr.narrative.routing import simple_action

            local = simple_action(action)
            if local:
                intent = local.command
        if intent_source not in {"direct", "model", "local-fallback", "local-correction"}:
            raise ValueError("Invalid interpretation source")
        command = intent or normalise_action(action)
        if self._gameplay is not None:
            from rpg_vkr.domain.combat import ATTACK_COMMANDS

            target = ATTACK_COMMANDS.get(command) or self._gameplay["state"]["active"]
            if command in ATTACK_COMMANDS or command == "атаковать":
                return self.perform_gameplay(
                    "attack",
                    {"target": target, "lethal": 0},
                    "cmd_" + self._request_token(),
                    action=action,
                )
            modes = {"уклониться": "dodge", "отступить": "retreat", "использовать бинт": "bandage"}
            if command in modes and self._gameplay["state"]["active"]:
                return self.perform_gameplay(
                    modes[command], {}, "cmd_" + self._request_token(), action=action
                )
            if self._gameplay["state"]["active"] and command not in {
                "состояние",
                "инвентарь",
                "помощь",
                "осмотреться",
                "спросить мастера",
            }:
                raise ValueError("Идёт бой по новым правилам: используйте боевые действия.")
            if command in {
                "подкрасться к волку",
                "подкрасться к кабану",
                "подкрасться к стражнику",
                "подкрасться к жительнице",
                "подкрасться к торговцу",
            }:
                raise ValueError("Скрытный подход прежней системы недоступен в новых правилах.")
        if not isinstance(origin, str) or origin not in {"typed", "quick", "system"}:
            raise ValueError("Invalid input origin")
        binding_error = (
            validate_binding(
                action,
                command,
                location=self.world.location,
                active_target=self.combat.active,
                interlocutor=last_interlocutor(self),
            )
            if intent is not None
            and not _verified_step
            and not (meaning and meaning.kind == "master")
            else None
        )
        if binding_error:
            command = intent = "уточнить намерение"
            meaning = None
        if self.schema_version >= 25 and command in {
            "помочь разгрузить телегу",
            "исследовать дорогу",
            "изучить учебник",
        }:
            if command == "изучить учебник":
                raise ValueError(
                    "В новых правилах обучение идёт через навыки и подтверждённые проверки."
                )
            if self.generated_world or self.world.location != (
                "gate" if command == "помочь разгрузить телегу" else "road"
            ):
                raise ValueError("Это занятие относится к прежнему учебному эпизоду.")
            return self.submit_challenge(
                action,
                assessment={
                    "ability": "strength" if command == "помочь разгрузить телегу" else "wisdom",
                    "dc": 10 if command == "помочь разгрузить телегу" else 12,
                    "purpose": "Помощь с телегой"
                    if command == "помочь разгрузить телегу"
                    else "Исследование дороги",
                    "skill": "athletics" if command == "помочь разгрузить телегу" else "survival",
                },
            )
        if (
            self.schema_version >= 25
            and command in {"купить бинт", "продать бинт", "торговля"}
            and not self.actor_is_here("merchant")
        ):
            raise ValueError("Торговый контакт закрыт: торговец отсутствует или отдыхает.")
        campaign_before = self.campaign
        if profile is not None:
            if (
                not isinstance(profile, NPCProfile)
                or not meaning
                or profile.actor_id != meaning.target
                or profile.created_at_turn != len(self.turns) + 1
                or not self.actor_is_here(profile.actor_id)
            ):
                raise ValueError("NPC proposal does not match this scene")
            candidate = self.campaign.add(profile)
        else:
            candidate = self.campaign
        if (
            meaning
            and meaning.target
            and self.actor_is_here(meaning.target)
            and not candidate.profile(meaning.target)
            and meaning.speech_act == "question"
            and meaning.topic in {"appearance", "background", "other"}
        ):
            candidate = candidate.add(
                procedural_profile(candidate, meaning.target, len(self.turns) + 1)
            )
        checkpoint = self.dice.checkpoint()
        before = snapshot(self.world, self.character, self.combat, self.progress)
        try:
            self.campaign = candidate
            turn, world = self._resolve_turn(action, command, meaning)
            turn = replace(
                turn,
                intent=intent,
                origin=origin,
                meaning=meaning,
                player_name=self.character.name,
                intent_source=intent_source,
            )
            if binding_error:
                turn = replace(turn, text=binding_error)
            combat = turn.combat.outcome.state if turn.combat is not None else self.combat
            progress = self.progress
            character = self.character
            activity = None
            if progress.enabled and self.schema_version < 25:
                if (
                    turn.combat is not None
                    and turn.combat.outcome.victory
                    and turn.actor_id == "wolf"
                    and not progress.practiced("wolf")
                ):
                    activity = "wolf"
                elif command == "исследовать дорогу" and turn.check is not None:
                    activity = "road"
                elif command == "помочь разгрузить телегу" and turn.check is not None:
                    activity = "cart"
                elif command == "изучить учебник" and turn.text.startswith("Вы изучили учебник."):
                    activity = "book"
            if activity is not None:
                progress = progress.award(
                    activity,
                    len(self._turns) + 1,
                    turn.check,
                    turn.roll.index if turn.roll else None,
                )
                character = progress.character()
                event = progress.events[-1]
                world = replace(world, max_hp=world.max_hp + event.max_hp_delta)
                turn = replace(turn, text=turn.text + "\n" + describe_award(event))
            resource_scene = (
                reconcile(
                    self.interactive_world, self.world, world, len(self.turns) + 1, self.catalog
                )
                if self.interactive_world
                else None
            )
            memory = self.memory.append(turn, before, snapshot(world, character, combat, progress))
        except Exception:
            self.campaign = campaign_before
            self.dice.restore(checkpoint)
            raise
        self.memory = memory
        if resource_scene:
            self.interactive_world = resource_scene
        if self.interactive_world and world.location != self.world.location:
            self.interactive_world = replace(self.interactive_world, current=world.location)
        self.world = world
        self.combat = combat
        self.progress = progress
        self.character = character
        self._turns.append(turn)
        return self._finish_turn(turn)

    def submit_actions(self, action):
        """Validate explicit local evidence and commit at most two steps atomically.

        There is no model-controlled bypass. The plan is recomputed here, using
        the current scene, inventory and interlocutor, before any dice are rolled.
        """
        from rpg_vkr.narrative.actions import action_plan

        action = _text(action, 500).strip()
        plan = action_plan(self, action)
        if plan is None:
            raise ValueError("Нет подтверждённого локального действия.")
        if plan.clarification:
            raise ValueError(plan.clarification)
        if len(self.turns) + len(plan.commands) > self.history_limit:
            raise ValueError("Достигнут предел действий. Сохраните сессию.")
        state = (
            self.world,
            self.character,
            self.combat,
            self.progress,
            self.campaign,
            self.memory,
            self.interactive_world,
        )
        checkpoint, count = self.dice.checkpoint(), len(self.turns)
        result = []
        try:
            for index, command in enumerate(plan.commands):
                # Do not grant the second action if travel failed or the hero fell.
                if index:
                    destination = {
                        "идти к воротам": "gate",
                        "идти на рынок": "market",
                        "идти на дорогу": "road",
                    }.get(plan.commands[index - 1])
                    if self.world.hp == 0 or (destination and self.world.location != destination):
                        break
                result.append(
                    self.submit(
                        action if index == 0 else command,
                        intent=command,
                        origin="typed" if index == 0 else "system",
                        intent_source="local-fallback",
                        _verified_step=True,
                    )
                )
            if plan.notes:
                result[-1] = replace(result[-1], notes=plan.notes)
                self._turns[-1] = result[-1]
        except Exception:
            (
                self.world,
                self.character,
                self.combat,
                self.progress,
                self.campaign,
                self.memory,
                self.interactive_world,
            ) = state
            del self._turns[count:]
            self.dice.restore(checkpoint)
            raise
        return tuple(result)

    def submit_scene(self, action, proposal, model, *, base_turn, instruction_hash=""):
        """Commit validated fiction and its visible segments in one transaction."""
        from rpg_vkr.narrative.context import build_frame
        from rpg_vkr.narrative.segments import split_story
        from rpg_vkr.narrative.speech import speech_details

        action = _text(action, 500)
        from rpg_vkr.narrative.actions import action_plan

        if action_plan(self, action) is not None:
            raise ValueError("Это действие требует игровых правил, а не свободной сцены.")
        record = SceneRecord(base_turn, self.world.location, model, proposal)
        if proposal.focus_id and not self.actor_is_here(proposal.focus_id):
            raise ValueError("Собеседника нет в текущем месте.")
        validate_scene(
            record,
            self.turns,
            self.world.location,
            self.combat,
            self.world.hp,
            scene=self.interaction_state(),
            catalog=self.catalog,
        )
        target = proposal.focus_id
        dialogue = None
        if target:
            act, topic = speech_details(action)
            if act == "contact" and "спро" in action.casefold():
                act, topic = "question", "other"
            from rpg_vkr.domain.social import grievance_after

            before = grievance(self.turns, target)
            dialogue = DialogueRecord(
                target, act, topic, before, grievance_after(before, act), "homebrew-social-2"
            )
        turn = Turn(
            action,
            "Рассказчик",
            proposal.narration,
            actor_id=target or None,
            dialogue=dialogue,
            player_name=self.character.name,
            intent_source="model",
            scene=record,
        )
        state = snapshot(self.world, self.character, self.combat, self.progress)
        memory = self.memory.append(turn, state, state)
        old_memory = self.memory
        self._turns.append(turn)
        self.memory = memory
        try:
            self.add_narration(
                Narration(
                    len(self.turns),
                    model,
                    proposal.narration,
                    build_frame(self).fingerprint,
                    segments=split_story(
                        proposal.narration,
                        target,
                        next(
                            (a.name for a in self.interaction_state().actor_refs if a.id == target),
                            None,
                        ),
                    ),
                    instruction_hash=instruction_hash,
                )
            )
        except Exception:
            self._turns.pop()
            self.memory = old_memory
            raise
        return turn

    def _resolve_turn(self, action: str, command: str, meaning=None) -> tuple[Turn, WorldState]:
        from rpg_vkr.domain.combat import ANGER_COMMANDS, ATTACK_COMMANDS, STEALTH_COMMANDS

        if self.generated_world and command in {
            "идти к воротам",
            "идти на дорогу",
            "идти на рынок",
            "исследовать дорогу",
            "взять поручение",
            "доставить корзину",
            "купить бинт",
            "продать бинт",
            "подойти к торговцу",
            "торговля",
            "узнать дорогу на рынок",
            "помочь разгрузить телегу",
        }:
            return Turn(
                action,
                "Рассказчик",
                (
                    "Опишите действие в текущем месте; этот маршрут относится к "
                    "прежнему учебному эпизоду."
                ),
            ), self.world

        target = (
            ATTACK_COMMANDS.get(command)
            or ANGER_COMMANDS.get(command)
            or STEALTH_COMMANDS.get(command)
            or CHAT_TARGETS.get(command)
            or NPC_CONTACTS.get(command)
        )
        if target and not self.actor_is_here(target):
            return Turn(
                action, "Рассказчик", "Этого персонажа здесь нет. Разговор или действие недоступны."
            ), self.world
        if command in COMBAT_COMMANDS or (
            self.combat.active is not None and command == "использовать бинт"
        ):
            outcome = perform_combat(
                self.combat, self.world, self.character, self.progress.class_id, command, self.dice
            )
            record = CombatRecord(
                self.combat, self.world, self.character, self.progress.class_id, command, outcome
            )
            speaker = ACTORS[outcome.actor_id][0] if outcome.actor_id else "Система"
            turn = Turn(
                action,
                speaker,
                outcome.text,
                outcome.rolls[0] if outcome.rolls else None,
                outcome.check,
                outcome.actor_id,
                record,
            )
            return turn, outcome.world
        information = {
            "состояние",
            "инвентарь",
            "задание",
            "развитие",
            "помощь",
            "спросить мастера",
            *OBSERVE_COMMANDS,
            *WHERE_COMMANDS,
        }
        if self.world.hp == 0 and command not in information:
            return Turn(
                action, "Рассказчик", "Вы выбыли. Загрузите сохранение или создайте нового героя."
            ), self.world
        if self.combat.active is not None and command not in information:
            return Turn(
                action,
                "Рассказчик",
                "Идёт схватка: атакуйте, уклонитесь, используйте бинт или отступите.",
            ), self.world
        if command == INSPECT_COMMAND:
            abilities = requested_abilities(action) or ("intelligence",)
            previous = next(
                (
                    t.inspection
                    for t in reversed(self.turns)
                    if t.inspection
                    and t.inspection.location == self.world.location
                    and set(t.inspection.abilities) == set(abilities)
                ),
                None,
            )
            if previous:
                return Turn(
                    action, "Рассказчик", "Вы уже проверили эти детали.\n" + previous.story()
                ), self.world
            record = inspect(self.world, self.character, self.dice, abilities)
            world = replace(self.world, market_known=True) if record.reveals_route else self.world
            return Turn(action, "Рассказчик", record.story(), inspection=record), world
        if command == "спросить мастера":
            from rpg_vkr.narrative.master import master_reply

            return Turn(action, "Рассказчик", master_reply(self, meaning)), self.world
        if command == "уточнить намерение":
            return Turn(
                action, "Рассказчик", "Нужно уточнить намерение. Мир не изменён."
            ), self.world
        if command in CHAT_TARGETS or command in NPC_CONTACTS:
            speaker, text, actor_id, record = resolve_conversation(
                self,
                action,
                CHAT_TARGETS.get(command) or NPC_CONTACTS.get(command),
                contact=command in NPC_CONTACTS,
                meaning=meaning,
            )
            return Turn(action, speaker, text, actor_id=actor_id, dialogue=record), self.world
        intent = dialogue_intent(action) if command == normalise_action(action) else None
        if intent is not None and command not in WORLD_COMMANDS:
            target, topic = intent
            speaker, text, actor_id, record = resolve_conversation(
                self, action, target, topic_hint=topic
            )
            return Turn(action, speaker, text, actor_id=actor_id, dialogue=record), self.world
        resident = None
        if (
            command in {"подойти к торговцу", "торговля", "купить бинт", "продать бинт"}
            and self.world.location == "market"
        ):
            resident = "merchant"
        elif (
            command
            in {
                "взять поручение",
                "поговорить с жительницей",
                "помочь",
                "помочь жительнице",
                "помочь собрать яблоки",
            }
            and self.world.location == "gate"
        ):
            resident = "villager"
        elif (
            command in {"узнать дорогу на рынок", "поговорить со стражником"}
            and self.world.location == "gate"
        ):
            resident = "guard"
        elif command == "поговорить":
            resident = {"gate": "guard", "market": "merchant"}.get(self.world.location)
        if resident is not None:
            actor = self.combat.actor(resident)
            if actor.hp == 0 or actor.disposition == "hostile":
                name = ACTORS[resident][0]
                text = f"{name}: мирное взаимодействие недоступно — " + (
                    "персонаж повержен." if actor.hp == 0 else "персонаж враждебен."
                )
                return Turn(action, name, text, actor_id=resident), self.world
            if grievance(self.turns, resident) >= 2:
                name = ACTORS[resident][0]
                return Turn(
                    action,
                    name,
                    f"{name}: после грубости разговор и помощь пока недоступны.",
                    actor_id=resident,
                ), self.world
        if command in PRACTICE_COMMANDS:
            return self._practice(action, command)
        if command in WORLD_COMMANDS:
            outcome = perform_action(self.world, command, self.character, self.dice)
            text = outcome.text
            if command in OBSERVE_COMMANDS:
                if self.interactive_world:
                    from rpg_vkr.narrative.context import build_frame

                    text = build_frame(self).scene
                else:
                    text = describe_scene(self.world)
                visible = [actor for actor in self.combat.actors if self.actor_is_here(actor.id)]
                text += "\n" + "\n".join(
                    f"{ACTORS[actor.id][0]}: {disposition_label(actor).lower()}, "
                    f"{health_description(actor)}."
                    for actor in visible
                )
            if self.generated_world and command in WHERE_COMMANDS:
                text = "Вы здесь: " + self.current_place_name + "."
            if command == "инвентарь" and self.extra_items:
                text += "; " + "; ".join(
                    f"{name} ×{quantity}" for name, quantity, _ in self.extra_inventory_rows
                )
            speaker = next((name for name in NPC_SPEAKERS if text.startswith(name + ":")), "Мир")
            turn = Turn(
                action, speaker, text, outcome.roll, outcome.check, NAMES_TO_IDS.get(speaker)
            )
            return turn, outcome.state
        elif command in ROLL_COMMANDS:
            roll = self.dice.roll_d20()
            turn = Turn(action, "Кубик", f"d20 → {roll.value}", roll)
        elif command in CHECK_COMMANDS:
            ability = CHECK_COMMANDS[command]
            roll = self.dice.roll_d20()
            check = resolve_ability_check(ability, self.character.score(ability), roll.value, 10)
            turn = Turn(action, "Правила", describe_check(check, roll.value), roll, check)
        else:
            turn = Turn(action, "Рассказчик", respond(action))
        return turn, self.world

    def _practice(self, action: str, command: str) -> tuple[Turn, WorldState]:
        if command == "развитие":
            return Turn(action, "Система", describe_progress(self.progress)), self.world
        if not self.progress.enabled:
            return Turn(action, "Рассказчик", describe_progress(self.progress)), self.world
        activity = "book" if command == "изучить учебник" else "cart"
        if self.progress.practiced(activity):
            return Turn(
                action, "Рассказчик", "Это занятие уже учтено. Повторного опыта и броска нет."
            ), self.world
        if activity == "book":
            return Turn(
                action, "Мир", "Вы изучили учебник. Учебный раздел об арифметике разобран."
            ), self.world
        if self.world.location != "gate":
            return Turn(
                action, "Рассказчик", "Телега осталась у ворот. Сначала вернитесь туда."
            ), self.world
        roll = self.dice.roll_d20()
        check = resolve_ability_check("strength", self.character.strength, roll.value, 10)
        consequence = (
            "Вы уверенно помогли разгрузить телегу."
            if check.succeeded
            else "Тяжёлые тюки не поддались. Вы помогли с лёгкими и разобрали ошибки."
        )
        text = describe_check(check, roll.value) + "\n" + consequence
        return Turn(action, "Мир", text, roll, check), self.world

    def edit_character(self, character: Character) -> bool:
        if self.in_combat or self.world.hp == 0:
            raise ValueError("Редактирование недоступно во время схватки или после поражения.")
        if self.progress.enabled:
            raise ValueError(
                "Созданный герой развивается действиями; "
                "свободный редактор доступен только песочнице."
            )
        if not isinstance(character, Character):
            raise ValueError("Invalid character")
        if character == self.character:
            return False
        if len(self._turns) >= self.history_limit:
            raise ValueError("Достигнут предел действий. Сохраните сессию и начните новую.")
        summary = "; ".join(
            f"{label}: {character.score(key)}" for key, label in ABILITY_NAMES.items()
        )
        turn = Turn(
            "Изменить персонажа",
            "Система",
            f"Профиль изменён: {character.name}. {summary}.",
            origin="system",
        )
        before = snapshot(self.world, self.character, self.combat, self.progress)
        memory = self.memory.append(
            turn, before, snapshot(self.world, character, self.combat, self.progress)
        )
        self.memory = memory
        self.character = character
        self._turns.append(turn)
        return True

    @property
    def narrations(self):
        return tuple(self._narrations)

    def add_narration(self, narration: Narration) -> None:
        if not isinstance(narration, Narration) or narration.turn_index != len(self._turns):
            raise ValueError("Narration refers to an outdated scene")
        if any(old.turn_index == narration.turn_index for old in self._narrations):
            raise ValueError("This scene already has narration")
        from rpg_vkr.narrative.context import build_frame

        if narration.context_hash != build_frame(self).fingerprint:
            raise ValueError("Narration context no longer matches")
        self._validate_segments(narration)
        self._narrations.append(narration)

    def _validate_segments(self, note):
        turn = self.turns[note.turn_index - 1] if note.turn_index else None
        target = turn.dialogue.target if turn and turn.dialogue else None
        if any(segment.speaker_id not in {"master", target} for segment in note.segments):
            raise ValueError("Narration contains an unapproved speaker")
        if target:
            actor = next((a for a in self.interaction_state().actor_refs if a.id == target), None)
            if not actor or any(
                s.speaker_id == target and s.display_name != actor.name for s in note.segments
            ):
                raise ValueError("Narration speaker identity differs from the scene")

    def to_dict(self) -> dict:
        if hasattr(self, "_fork"):
            from rpg_vkr.storage.migration import serialize

            return serialize(self)
        return self._plain_dict()

    def _plain_dict(self) -> dict:
        value = {
            "chronicle": self.chronicle.to_dict() if self.chronicle else None,
            "catalog": self.catalog.to_dict() if self.catalog else None,
            "interactive_world": self.interactive_world.to_dict()
            if self.interactive_world
            else None,
            "campaign": self.campaign.to_dict(),
            "memory": self.memory.to_dict(),
            "narrations": [note.to_dict() for note in self.narrations],
            "seed": self.dice.seed,
            "character": asdict(self.character),
            "world": asdict(self.world),
            "progress": self.progress.to_dict(),
            "combat": self.combat.to_dict(),
            "introduction": self.introduction,
            "turns": [
                asdict(turn)
                | {
                    "combat": turn.combat.to_dict() if turn.combat else None,
                    "interaction": turn.interaction.to_dict() if turn.interaction else None,
                    "catalog": turn.catalog.to_dict() if turn.catalog else None,
                    "trade": turn.trade.to_dict() if turn.trade else None,
                    "challenge": turn.challenge.to_dict() if turn.challenge else None,
                }
                for turn in self._turns
            ],
        }

        if self._gameplay is None:
            for item in value["turns"]:
                item.pop("gameplay")
        else:
            from copy import deepcopy

            value["gameplay"] = deepcopy(self._gameplay)
        if self._d20_progress is not None:
            value["d20_progress"] = self.d20_progress.to_dict()
        return value

    @classmethod
    def from_dict(cls, data: object, version: int | None = None) -> "Session":
        if isinstance(data, dict) and "unified" in data:
            if version not in (None, 30, 31):
                raise ValueError("Единая кампания требует схему30.")
            from rpg_vkr.unified_session import restore

            restored = restore(data)
            if version is not None and restored.schema_version != version:
                raise ValueError("Схема не соответствует содержимому кампании.")
            return restored
        if isinstance(data, dict) and "fork" in data:
            if version not in (None, 29):
                raise ValueError("Копия требует схему29.")
            from rpg_vkr.storage.migration import restore

            return restore(data)
        if version is None:
            from rpg_vkr.domain.gameplay_rules import revision as saved_revision

            version = (
                23 + saved_revision(data["gameplay"]["state"])
                if isinstance(data, dict) and "gameplay" in data
                else 23
                if isinstance(data, dict) and "d20_progress" in data
                else 22
            )
        if type(version) is not int or version not in (
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
            16,
            17,
            18,
            19,
            20,
            21,
            22,
            23,
            24,
            25,
            26,
            27,
            28,
        ):
            raise ValueError("Unsupported session version")
        keys = {"seed", "introduction", "turns"}
        if version >= 24:
            keys.add("gameplay")
        if version >= 23:
            keys.add("d20_progress")
        if version >= 21:
            keys.add("chronicle")
        if version >= 19:
            keys.add("catalog")
        if version >= 18:
            keys.add("interactive_world")
        if version >= 10:
            keys.add("campaign")
        if version >= 7:
            keys.update({"memory", "narrations"})
        if version >= 2:
            keys.add("character")
        if version >= 3:
            keys.add("world")
        if version >= 5:
            keys.add("progress")
        if version >= 6:
            keys.add("combat")
        if not isinstance(data, dict) or set(data) != keys:
            raise ValueError("Invalid session structure")
        # A missing seed must never silently create a new random sequence.
        if type(data["seed"]) is not int:
            raise ValueError("Missing session seed")
        character = Character() if version == 1 else Character.from_dict(data["character"])
        if version < 3:
            world = WorldState()
        elif version == 3:
            old_world = data["world"]
            legacy_keys = set(asdict(WorldState())) - {"market_known", "trading"}
            if not isinstance(old_world, dict) or set(old_world) != legacy_keys:
                raise ValueError("Invalid legacy world")
            # Old worlds had public navigation; preserve access without replaying history.
            world = WorldState.from_dict(old_world | {"market_known": True, "trading": False})
        else:
            world = WorldState.from_dict(data["world"])
        session = cls(seed=data["seed"], character=character, world=world)
        if version >= 23:
            from rpg_vkr.domain.d20_progression import D20Progress

            session._d20_progress = D20Progress.from_dict(data["d20_progress"])
        if version >= 24:
            from rpg_vkr.domain.gameplay_rules import restore_initial

            raw = data["gameplay"]
            if not isinstance(raw, dict) or set(raw) != {"identity", "state"}:
                raise ValueError("Неверный формат новых игровых правил.")
            initial_hero = Character.from_dict(data["progress"]["initial"])
            session._gameplay = {
                "identity": raw["identity"],
                "state": restore_initial(raw["identity"], initial_hero, raw["state"], version),
            }
        session.campaign = (
            Campaign.from_dict(data["campaign"]) if version >= 10 else Campaign.migrate(data)
        )
        session.chronicle = (
            Chronicle.from_dict(data["chronicle"]) if version >= 21 and data["chronicle"] else None
        )
        if session.generated_world:
            seed = session.chronicle.seed
            class_id = data["progress"]["class_id"]
            if (
                seed.signature != input_signature(session.campaign, class_id)
                or data["introduction"] != seed.opening
            ):
                raise ValueError("Происхождение мира не совпадает с героем.")
            session.catalog = seed.catalog
            if version >= 26:
                from rpg_vkr.domain.factions import initialize

                session._gameplay["state"] = initialize(
                    session._gameplay["state"], seed.catalog, seed.scene
                )
        if version < 17 and session.campaign.version != "campaign-1":
            raise ValueError("World brief requires session schema 17")
        session.introduction = _text(data["introduction"], 4000)
        turns = data["turns"]
        if not isinstance(turns, list) or len(turns) > MAX_TURNS:
            raise ValueError("Invalid turn history")
        previous_item = None
        for item in turns:
            if version >= 24 and previous_item:
                from rpg_vkr.gameplay_session import restore_clock

                restore_clock(session, previous_item)
            previous_item = item
            turn_keys = {"action", "speaker", "text", "roll"}
            if version >= 24:
                turn_keys.add("gameplay")
            if version >= 21:
                turn_keys.add("trade")
            if version >= 19:
                turn_keys.add("catalog")
            if version >= 18:
                turn_keys.add("interaction")
            if version >= 17:
                turn_keys.add("challenge")
            if version >= 16:
                turn_keys.add("notes")
            if version >= 12:
                turn_keys.add("scene")
            if version >= 11:
                turn_keys.update({"inspection", "intent_source"})
            if version >= 10:
                turn_keys.update({"meaning", "player_name"})
            if version >= 9:
                turn_keys.update({"origin", "dialogue"})
            if version >= 8:
                turn_keys.add("intent")
            if version >= 2:
                turn_keys.add("check")
            if version >= 6:
                turn_keys.update({"actor_id", "combat"})
            if not isinstance(item, dict) or set(item) != turn_keys:
                raise ValueError("Invalid turn")
            if (
                version >= 24
                and item["gameplay"] is not None
                and not isinstance(item["gameplay"], dict)
            ):
                raise ValueError("Неверный формат записи игровых правил.")
            action = _text(item["action"], 500)
            intent = item.get("intent")
            if intent is not None and (
                not isinstance(intent, str) or intent not in allowed_intents()
            ):
                raise ValueError("Invalid resolved intent")
            command = intent or normalise_action(action)
            meaning = None
            if version >= 10 and item["meaning"] is not None:
                from rpg_vkr.narrative.routing import meaning_command

                meaning = Meaning.from_dict(item["meaning"])
                if (
                    command != meaning_command(meaning)
                    or item["combat"] is not None
                    or item["roll"] is not None
                ):
                    raise ValueError("Saved meaning does not match this turn")
            intent_source = item.get("intent_source", "legacy")
            if not isinstance(intent_source, str) or intent_source not in {
                "direct",
                "model",
                "local-fallback",
                "local-correction",
                "legacy",
            }:
                raise ValueError("Invalid saved interpretation source")
            player_name = item.get("player_name")
            if player_name is not None:
                player_name = _text(player_name, 40)
            origin = item.get("origin", "legacy")
            if not isinstance(origin, str) or origin not in {"typed", "quick", "legacy", "system"}:
                raise ValueError("Invalid saved input origin")
            dialogue = None
            if version >= 9 and item["dialogue"] is not None:
                dialogue = DialogueRecord.from_dict(item["dialogue"])
                if version < 22 and dialogue.rules_version != "homebrew-social-1":
                    raise ValueError("New conversation requires schema 22")
                if (
                    dialogue.before != grievance(session.turns, dialogue.target)
                    or item["actor_id"] != dialogue.target
                    or item["roll"] is not None
                    or item["check"] is not None
                    or item["combat"] is not None
                ):
                    raise ValueError("Invalid social history")
                if command_target(command) not in {None, dialogue.target}:
                    raise ValueError("Social target does not match intent")
                # The recorded interpretation is historical evidence. Do not reinterpret
                # natural language on load after a future parser/model improvement.
            if meaning:
                if meaning.kind == "master" and (
                    item["actor_id"] is not None or dialogue is not None
                ):
                    raise ValueError("Master question cannot impersonate an NPC")
                if dialogue and (
                    meaning.kind != "dialogue"
                    or meaning.target != dialogue.target
                    or meaning.speech_act != dialogue.act
                    or meaning.topic != dialogue.topic
                ):
                    raise ValueError("Social record does not match saved semantics")
            text = _text(item["text"], 16000 if version >= 22 else 4000)
            roll = None
            check = None
            stored_check = item.get("check")
            if (
                version >= 24
                and item["gameplay"] is not None
                and item["gameplay"].get("command") != "advance"
            ):
                from rpg_vkr.gameplay_session import restore_turn

                restore_turn(session, item)
                continue
            if version >= 21 and item["trade"] is not None:
                if item["speaker"] != "Мир" or any(
                    item[k] is not None
                    for k in (
                        "actor_id",
                        "roll",
                        "check",
                        "intent",
                        "meaning",
                        "dialogue",
                        "combat",
                        "inspection",
                        "scene",
                        "challenge",
                        "interaction",
                        "catalog",
                    )
                ):
                    raise ValueError("Сделка смешана с другим действием.")
                session.catalog, record = restore_trade(
                    item["trade"], session.catalog or seed_catalog(), session.catalog_aliases
                )
                if record.base_turn != len(session.turns) or record.summary != text:
                    raise ValueError("Сделка не совпадает с записью хода.")
                session._turns.append(
                    Turn(
                        action,
                        "Мир",
                        text,
                        origin=origin,
                        player_name=player_name,
                        intent_source=intent_source,
                        trade=record,
                    )
                )
                continue
            if version >= 19 and item["catalog"] is not None:
                if isinstance(item["catalog"], dict) and "operation" in item["catalog"]:
                    if (
                        item["speaker"] != "Мир"
                        or item["actor_id"] is not None
                        or any(
                            item[k] is not None
                            for k in (
                                "intent",
                                "meaning",
                                "dialogue",
                                "combat",
                                "inspection",
                                "scene",
                                "challenge",
                                "interaction",
                            )
                        )
                    ):
                        raise ValueError("Actor attempt mixed with another action")
                    session.catalog, _, record = restore_attempt(
                        item["catalog"], session.catalog or seed_catalog(), session.dice, character
                    )
                    if (
                        record.base_turn != len(session.turns)
                        or record.summary != text
                        or item["roll"] != asdict(record.roll)
                        or stored_check != asdict(record.check)
                    ):
                        raise ValueError("Actor attempt turn mismatch")
                    if record.target_id in ACTORS:
                        actor = session.combat.actor(record.target_id)
                        session.combat = session.combat.update(
                            replace(
                                actor,
                                hp=record.entity_after.state["hp"],
                                disposition=record.entity_after.state["disposition"],
                            )
                        )
                    session._turns.append(
                        Turn(
                            action,
                            "Мир",
                            text,
                            record.roll,
                            record.check,
                            origin=origin,
                            player_name=player_name,
                            intent_source=intent_source,
                            catalog=record,
                        )
                    )
                    continue
                if (
                    item["speaker"] != "Мир"
                    or item["actor_id"] is not None
                    or any(
                        item[k] is not None
                        for k in (
                            "roll",
                            "check",
                            "intent",
                            "meaning",
                            "dialogue",
                            "combat",
                            "inspection",
                            "scene",
                            "challenge",
                            "interaction",
                        )
                    )
                ):
                    raise ValueError("Catalog registration mixed with another action")
                record = Registration.from_dict(item["catalog"])
                if record.base_turn != len(session.turns):
                    raise ValueError("Catalog registration has the wrong turn")
                session.catalog, _ = register(
                    session.catalog or seed_catalog(), record.before, record
                )
                names = {d.id: d.name for d in session.catalog.definitions}
                expected = (
                    "Вы замечаете: "
                    + "; ".join(names[e.definition_id] for e in record.entities)
                    + "."
                    if record.entities
                    else "Сохранены сведения: "
                    + "; ".join(d.name for d in record.definitions)
                    + "."
                )
                if text != expected:
                    raise ValueError("Catalog registration text mismatch")
                session._turns.append(
                    Turn(
                        action,
                        "Мир",
                        text,
                        origin=origin,
                        player_name=player_name,
                        intent_source=intent_source,
                        catalog=record,
                    )
                )
                continue
            if version >= 18 and item["interaction"] is not None:
                if (
                    item["speaker"] != "Мир"
                    or intent is not None
                    or meaning is not None
                    or dialogue is not None
                    or item["actor_id"] is not None
                    or any(
                        item[k] is not None for k in ("combat", "inspection", "scene", "challenge")
                    )
                ):
                    raise ValueError("Interaction mixed with another action")
                record = Interaction.restore(
                    item["interaction"], session.dice, len(session.turns) + 1
                )
                if session.catalog and record.before.version == "interactive-world-4":
                    from rpg_vkr.domain.npc_reactions import react

                    session.catalog = react(session.catalog, record, len(session.turns) + 1)
                if session.catalog or physical(record.before):
                    validate_plan_properties(
                        session.catalog or seed_catalog(),
                        record.before,
                        record.plan,
                        turn_index=len(session.turns) + 1,
                        aliases=session.catalog_aliases,
                    )
                if (
                    item["roll"] != (asdict(record.roll) if record.roll else None)
                    or stored_check != (asdict(record.check) if record.check else None)
                    or text != record.summary
                ):
                    raise ValueError("Interaction turn mismatch")
                session.combat = replace(
                    session.combat,
                    actors=tuple(
                        replace(a, disposition="hostile")
                        if a.id in record.witnesses and a.hp > 0
                        else a
                        for a in session.combat.actors
                    ),
                )
                session._turns.append(
                    Turn(
                        action,
                        "Мир",
                        text,
                        record.roll,
                        record.check,
                        origin=origin,
                        player_name=player_name,
                        intent_source=intent_source,
                        interaction=record,
                    )
                )
                continue
            if version >= 17 and item["challenge"] is not None:
                if (
                    item["speaker"] != "Правила"
                    or intent is not None
                    or meaning is not None
                    or dialogue is not None
                    or item["actor_id"] is not None
                    or any(item[k] is not None for k in ("combat", "inspection", "scene"))
                ):
                    raise ValueError("Challenge mixed with another action")
                record = Challenge.restore(item["challenge"], session.dice)
                if record.version == "challenge-homebrew-3" and version < 23:
                    raise ValueError("Проверка навыка требует схему 23.")
                if version < 22 and record.assessment is not None:
                    raise ValueError("General assessment requires schema 22")
                if (
                    item["roll"] != asdict(record.roll)
                    or stored_check != asdict(record.check)
                    or text != record.story()
                ):
                    raise ValueError("Challenge turn mismatch")
                session._turns.append(
                    Turn(
                        action,
                        item["speaker"],
                        text,
                        record.roll,
                        record.check,
                        origin=origin,
                        player_name=player_name,
                        intent_source=intent_source,
                        challenge=record,
                    )
                )
                continue
            if version >= 12 and item["scene"] is not None:
                record = SceneRecord.from_dict(item["scene"])
                if version < 22 and record.version == "scene-director-6":
                    raise ValueError("New scene requires session schema 22")
                if (
                    record.base_turn != len(session.turns)
                    or text != record.proposal.narration
                    or item["speaker"] != "Рассказчик"
                    or intent is not None
                    or meaning is not None
                    or any(item[k] is not None for k in ("roll", "check", "combat", "inspection"))
                    or item["actor_id"] != (record.proposal.focus_id or None)
                    or (dialogue.target if dialogue else "") != record.proposal.focus_id
                ):
                    raise ValueError("Scene record does not match its turn")
                session._turns.append(
                    Turn(
                        action,
                        item["speaker"],
                        text,
                        actor_id=item["actor_id"],
                        origin=origin,
                        dialogue=dialogue,
                        player_name=player_name,
                        intent_source=intent_source,
                        scene=record,
                    )
                )
                continue
            if version >= 11 and item["inspection"] is not None:
                if (
                    command != INSPECT_COMMAND
                    or item["speaker"] != "Рассказчик"
                    or item["actor_id"] is not None
                    or item["roll"] is not None
                    or stored_check is not None
                    or item["combat"] is not None
                    or dialogue is not None
                    or meaning is not None
                ):
                    raise ValueError("Inspection mixed with another action")
                record = Inspection.restore(item["inspection"], session.dice)
                if text != record.story():
                    raise ValueError("Inspection text does not match checked discoveries")
                session._turns.append(
                    Turn(
                        action,
                        item["speaker"],
                        text,
                        intent=intent,
                        origin=origin,
                        player_name=player_name,
                        inspection=record,
                        intent_source=intent_source,
                    )
                )
                continue
            if version >= 6 and item["combat"] is not None:
                previous_record = next(
                    (turn.combat for turn in reversed(session._turns) if turn.combat), None
                )
                record = restore_record(item["combat"], command, session.combat, session.dice)
                if session.combat.active is not None and previous_record is not None:
                    if (
                        record.world_before != previous_record.outcome.world
                        or record.character != previous_record.character
                    ):
                        raise ValueError("Combat round inputs changed without an action")
                outcome = record.outcome
                first_roll = outcome.rolls[0] if outcome.rolls else None
                if (
                    canonical(item["roll"]) != canonical(asdict(first_roll) if first_roll else None)
                    or canonical(stored_check)
                    != canonical(asdict(outcome.check) if outcome.check else None)
                    or item["actor_id"] != outcome.actor_id
                    or item["speaker"]
                    != (ACTORS[outcome.actor_id][0] if outcome.actor_id else "Система")
                    or not (text == outcome.text or text.startswith(outcome.text + "\nРазвитие:"))
                ):
                    raise ValueError("Combat turn mismatch")
                session.combat = outcome.state
                session._turns.append(
                    Turn(
                        action,
                        item["speaker"],
                        text,
                        first_roll,
                        outcome.check,
                        outcome.actor_id,
                        record,
                        intent,
                        origin,
                        dialogue,
                        meaning,
                        player_name,
                        None,
                        intent_source,
                    )
                )
                continue
            if item["roll"] is not None:
                stored_roll = item["roll"]
                if not isinstance(stored_roll, dict) or set(stored_roll) != {"index", "value"}:
                    raise ValueError("Invalid roll")
                if any(type(value) is not int for value in stored_roll.values()):
                    raise ValueError("Invalid roll numbers")
                roll = session.dice.roll_d20()
                if stored_roll != asdict(roll):
                    raise ValueError("Dice history does not match the seed")
                if stored_check is not None:
                    check_keys = {
                        "ability",
                        "score",
                        "difficulty",
                        "modifier",
                        "total",
                        "succeeded",
                    }
                    if not isinstance(stored_check, dict) or set(stored_check) != check_keys:
                        raise ValueError("Invalid ability check")
                    if (
                        any(
                            type(stored_check[key]) is not int
                            for key in ("score", "difficulty", "modifier", "total")
                        )
                        or type(stored_check["succeeded"]) is not bool
                    ):
                        raise ValueError("Invalid check numbers")
                    world_check = (
                        version >= 3
                        and command
                        in (
                            {"исследовать дорогу"}
                            | ({"помочь разгрузить телегу"} if version >= 5 else set())
                        )
                        and item["speaker"] == "Мир"
                        and stored_check["ability"]
                        == ("dexterity" if command == "исследовать дорогу" else "strength")
                        and stored_check["difficulty"] == 10
                    )
                    if CHECK_COMMANDS.get(command) != stored_check["ability"] and not world_check:
                        raise ValueError("Check does not match action")
                    check = resolve_ability_check(
                        stored_check["ability"],
                        stored_check["score"],
                        roll.value,
                        stored_check["difficulty"],
                    )
                    expected = describe_check(check, roll.value)
                    valid_text = (
                        text.startswith(expected + "\n") if world_check else text == expected
                    )
                    valid_speaker = world_check or item["speaker"] == "Правила"
                    if stored_check != asdict(check) or not valid_text or not valid_speaker:
                        raise ValueError("Check does not match calculation")
                elif (
                    command not in ROLL_COMMANDS
                    or text != f"d20 → {roll.value}"
                    or item["speaker"] != "Кубик"
                ):
                    raise ValueError("Invalid dice turn")
            else:
                valid_speaker = (
                    item["speaker"] == "Рассказчик"
                    or (
                        version >= 3
                        and item["speaker"] == "Мир"
                        and command
                        in (WORLD_COMMANDS | (PRACTICE_COMMANDS if version >= 5 else set()))
                    )
                    or (
                        version >= 3
                        and item["speaker"] == "Система"
                        and (
                            action == "Изменить персонажа"
                            or (version >= 5 and command == "развитие")
                        )
                    )
                )
                if version >= 5 and item["speaker"] in NPC_SPEAKERS:
                    valid_speaker = (
                        command in WORLD_COMMANDS
                        or (version >= 7 and dialogue_intent(action) is not None)
                        or (version >= 8 and command in CHAT_TARGETS)
                        or (version >= 9 and command in NPC_CONTACTS)
                    ) and text.startswith(item["speaker"] + ":")
                if stored_check is not None or not valid_speaker:
                    raise ValueError("Invalid narration turn")
            actor_id = item.get("actor_id", NAMES_TO_IDS.get(item["speaker"]))
            if version >= 6 and actor_id != NAMES_TO_IDS.get(item["speaker"]):
                raise ValueError("Missing or changed actor identity")
            if actor_id is not None and (
                actor_id not in ACTORS or ACTORS[actor_id][0] != item["speaker"]
            ):
                raise ValueError("Actor identity mismatch")
            session._turns.append(
                Turn(
                    action,
                    item["speaker"],
                    text,
                    roll,
                    check,
                    actor_id,
                    intent=intent,
                    origin=origin,
                    dialogue=dialogue,
                    meaning=meaning,
                    player_name=player_name,
                    intent_source=intent_source,
                )
            )
        if version >= 24 and previous_item:
            from rpg_vkr.gameplay_session import restore_clock

            restore_clock(session, previous_item)
        if version >= 16:
            from rpg_vkr.narrative.actions import NOTES

            for index, item in enumerate(turns):
                notes = item["notes"]
                if (
                    not isinstance(notes, (list, tuple))
                    or len(notes) > len(NOTES)
                    or any(not isinstance(n, str) or n not in NOTES for n in notes)
                    or len(set(notes)) != len(notes)
                ):
                    raise ValueError("Invalid saved action notes")
                session._turns[index] = replace(session._turns[index], notes=tuple(notes))
        if version >= 5:
            session.progress = HeroProgress.from_dict(data["progress"], session.turns)
            if session.progress.enabled:
                if session.progress.character() != session.character:
                    raise ValueError("Character growth does not match recorded events")
                if version >= 25:
                    from rpg_vkr.domain.hero_resources import limits

                    caps = limits(
                        session._gameplay["state"], session.character, session.d20_progress.level
                    )
                    if session.progress.events or session.world.max_hp != caps["hp"]:
                        raise ValueError("Новые ресурсы не соответствуют развитию D20.")
                else:
                    expected_max = 12 + (2 if session.progress.level == 2 else 0)
                    if session.world.max_hp != expected_max:
                        raise ValueError("Health maximum does not match level")
                    eligible = {
                        index
                        for index, turn in enumerate(session.turns, 1)
                        if (
                            normalise_action(turn.intent or turn.action)
                            in {"исследовать дорогу", "помочь разгрузить телегу"}
                            and turn.check is not None
                        )
                        or (
                            normalise_action(turn.intent or turn.action) == "изучить учебник"
                            and turn.text.startswith("Вы изучили учебник.")
                        )
                    }
                    eligible.update(
                        index
                        for index, turn in enumerate(session.turns, 1)
                        if turn.combat and turn.combat.outcome.victory and turn.actor_id == "wolf"
                    )
                    if eligible != {event.turn_index for event in session.progress.events}:
                        raise ValueError("Missing or extra development events")
        if version >= 6:
            if CombatState.from_dict(data["combat"]) != session.combat:
                raise ValueError("Final combat state mismatch")
            if session.world.trading and (
                session.combat.actor("merchant").disposition == "hostile"
                or session.combat.actor("merchant").hp == 0
            ):
                raise ValueError("Trading with an unavailable merchant")
            if session.combat.active is not None:
                previous_record = next(
                    (turn.combat for turn in reversed(session._turns) if turn.combat), None
                )
                if previous_record is None or session.world != previous_record.outcome.world:
                    raise ValueError("Final world does not match active encounter")
                if (
                    session.world.hp == 0
                    or ACTORS[session.combat.active][1] != session.world.location
                ):
                    raise ValueError("Active combat context mismatch")
            for index, turn in enumerate(session.turns, 1):
                if turn.combat:
                    award = next(
                        (event for event in session.progress.events if event.turn_index == index),
                        None,
                    )
                    expected_text = turn.combat.outcome.text + (
                        "\n" + describe_award(award) if award else ""
                    )
                    if turn.text != expected_text:
                        raise ValueError("Combat explanation does not match development event")
                if turn.combat and session.progress.enabled:
                    before_progress = HeroProgress(
                        session.progress.class_id,
                        session.progress.initial,
                        tuple(
                            event for event in session.progress.events if event.turn_index < index
                        ),
                    )
                    if (
                        turn.combat.class_id != session.progress.class_id
                        or turn.combat.character != before_progress.character()
                    ):
                        raise ValueError("Combat character does not match progression")
        if any(p.created_at_turn > len(session.turns) for p in session.campaign.npc_profiles):
            raise ValueError("NPC canon is anchored in the future")
        for profile in session.campaign.npc_profiles:
            turn = session.turns[profile.created_at_turn - 1]
            if not turn.meaning or turn.meaning.target != profile.actor_id:
                raise ValueError("NPC profile has no matching confirmed question")
        final = snapshot(session.world, session.character, session.combat, session.progress)
        session.memory = (
            WorldMemory.from_dict(data["memory"], session.turns, final)
            if version >= 7
            else WorldMemory(len(session.turns), final)
        )
        fields = dict(session.memory.baseline)
        interactive = session.chronicle.seed.scene if session.generated_world else None
        historical_catalog = session.chronicle.seed.catalog if session.generated_world else None
        legacy_lives = {}
        historical_gameplay = None
        if version >= 24:
            from rpg_vkr.domain.gameplay_rules import restore_initial

            historical_gameplay = restore_initial(
                data["gameplay"]["identity"],
                session.progress.initial,
                data["gameplay"]["state"],
                version,
            )
        if version >= 26 and session.generated_world:
            from rpg_vkr.domain.factions import initialize

            historical_gameplay = initialize(
                historical_gameplay, session.chronicle.seed.catalog, session.chronicle.seed.scene
            )
        for event in session.memory.events:
            turn = session.turns[event.turn_index - 1]
            original_event = event
            before_fields = dict(fields)
            if version >= 25 and turn.gameplay and turn.gameplay["command"] == "advance":
                from rpg_vkr.domain.memory import Change

                primary_after = fields | {c.field: c.after for c in event.changes}
                primary_after.update(
                    {"world." + k: v for k, v in turn.gameplay["context"]["world"].items()}
                )
                event = replace(
                    event,
                    changes=tuple(
                        Change(k, fields[k], v)
                        for k, v in sorted(primary_after.items())
                        if fields[k] != v
                    ),
                )
            if turn.gameplay and turn.gameplay["command"] != "advance":
                from rpg_vkr.gameplay_session import validate_history

                expected_fields, interactive, historical_catalog = validate_history(
                    turn.gameplay,
                    fields,
                    interactive,
                    historical_catalog,
                    event.turn_index,
                    session.turns,
                )
                historical_gameplay = turn.gameplay["result"]["state"]
                if {c.field: (c.before, c.after) for c in event.changes} != {
                    k: (fields[k], v) for k, v in expected_fields.items() if fields[k] != v
                }:
                    raise ValueError("Новые правила изменили неподтверждённые поля.")
            elif turn.trade:
                record = turn.trade
                expected_before = interactive or InteractiveWorld.initial(fields["world.location"])
                world = WorldState.from_dict(
                    {k: fields["world." + k] for k in asdict(WorldState())}
                )
                if (
                    record.before != expected_before
                    or record.world_before != world
                    or fields["combat.active"] is not None
                    or world.hp <= 0
                ):
                    raise ValueError("Сделка не соответствует историческому состоянию.")
                aliases = {
                    f"split_{i}_{j}": step.target
                    for i, prior in enumerate(session.turns[: event.turn_index - 1], 1)
                    if prior.interaction
                    for j, step in enumerate(prior.interaction.plan.steps)
                }
                aliases.update(
                    {
                        f"split_{i}_0": prior.trade.item_id
                        for i, prior in enumerate(session.turns[: event.turn_index - 1], 1)
                        if prior.trade
                    }
                )
                historical_catalog, _, expected_record = transact(
                    historical_catalog or seed_catalog(),
                    expected_before,
                    world,
                    record.merchant_id,
                    record.item_id,
                    record.operation,
                    record.quantity,
                    event.turn_index,
                    record.source,
                    aliases,
                )
                if canonical(record.to_dict()) != canonical(expected_record.to_dict()):
                    raise ValueError("Сделка изменила непредусмотренные данные.")
                expected_fields = fields | {
                    "world." + k: v for k, v in asdict(record.world_after).items()
                }
                if {c.field: (c.before, c.after) for c in event.changes} != {
                    k: (fields[k], v) for k, v in expected_fields.items() if fields[k] != v
                }:
                    raise ValueError("Изменения ресурсов не соответствуют сделке.")
                interactive = record.after
            elif isinstance(turn.catalog, ActorAttempt):
                from rpg_vkr.domain.catalog import Entity

                record = turn.catalog
                expected_before = interactive or InteractiveWorld.initial(fields["world.location"])
                world = WorldState.from_dict(
                    {k: fields["world." + k] for k in asdict(WorldState())}
                )
                hero = Character.from_dict({k: fields["hero." + k] for k in asdict(Character())})
                legacy_entity = None
                if record.target_id in ACTORS:
                    key = record.target_id
                    state = {
                        "hp": fields[f"actor.{key}.hp"],
                        "disposition": fields[f"actor.{key}.disposition"],
                    }
                    if state["hp"] == 0 and legacy_lives.get(key) == "dead":
                        state["life"] = "dead"
                    legacy_entity = Entity(key, "type_actor_" + key, ACTORS[key][1], state=state)
                if fields["combat.active"] is not None or fields["world.hp"] <= 0:
                    raise ValueError("Actor attempt has invalid historical context")
                historical_catalog, after_world, expected_record = resolve_attempt(
                    historical_catalog or seed_catalog(),
                    expected_before,
                    world,
                    hero,
                    record.target_id,
                    record.operation,
                    record.lethal,
                    record.roll,
                    record.reason,
                    record.model,
                    record.base_turn,
                    legacy_entity,
                    counter_roll=record.counter.roll if record.counter else None,
                )
                if canonical(record.to_dict()) != canonical(expected_record.to_dict()):
                    raise ValueError("Actor attempt does not match historical calculation")
                if physical(expected_before):
                    interactive = reconcile(
                        expected_before, world, after_world, event.turn_index, historical_catalog
                    )
                expected_fields = dict(fields)
                expected_fields.update({"world." + k: v for k, v in asdict(after_world).items()})
                if record.target_id in ACTORS:
                    for key in ("hp", "disposition"):
                        expected_fields[f"actor.{record.target_id}.{key}"] = (
                            record.entity_after.state[key]
                        )
                    legacy_lives[record.target_id] = record.entity_after.state.get("life")
                if {c.field: (c.before, c.after) for c in event.changes} != {
                    k: (fields[k], v) for k, v in expected_fields.items() if fields[k] != v
                }:
                    raise ValueError("Actor attempt changed unapproved fields")
            elif turn.catalog:
                expected_before = interactive or InteractiveWorld.initial(fields["world.location"])
                if (
                    turn.catalog.before != expected_before
                    or event.changes
                    or fields["world.hp"] <= 0
                    or fields["combat.active"] is not None
                ):
                    raise ValueError("Catalog registration does not match historical scene")
                historical_catalog, interactive = register(
                    historical_catalog or seed_catalog(), expected_before, turn.catalog
                )
            elif turn.interaction:
                record = turn.interaction
                expected_before = interactive or InteractiveWorld.initial(fields["world.location"])
                if physical(record.before) and not physical(expected_before):
                    prior_world = WorldState.from_dict(
                        {k: fields["world." + k] for k in asdict(WorldState())}
                    )
                    aliases = {
                        f"split_{i}_{j}": step.target
                        for i, prior in enumerate(session.turns[: event.turn_index - 1], 1)
                        if prior.interaction
                        for j, step in enumerate(prior.interaction.plan.steps)
                    }
                    expected_before = activate_resources(
                        expected_before, prior_world, historical_catalog, aliases
                    )
                if (
                    record.before != expected_before
                    or fields["world.hp"] <= 0
                    or fields["combat.active"] is not None
                    or record.check
                    and record.check.score != fields["hero.dexterity"]
                ):
                    raise ValueError("Interaction does not match historical scene")
                expected_fields = dict(fields)
                anchor = record.after.place().anchor
                expected_fields.update(
                    {
                        "world.location": anchor,
                        "world.trading": (
                            False
                            if record.after.current != record.before.current
                            else fields["world.trading"]
                        ),
                        "world.market_known": fields["world.market_known"] or anchor == "market",
                    }
                )
                if physical(record.after):
                    from rpg_vkr.domain.resources import balances

                    expected_fields.update(
                        {"world." + k: v for k, v in balances(record.after).items()}
                    )
                for actor in record.witnesses:
                    if actor not in ACTORS:
                        continue
                    if fields[f"actor.{actor}.hp"] > 0:
                        expected_fields[f"actor.{actor}.disposition"] = "hostile"
                expected_changes = {
                    k: (fields[k], v) for k, v in expected_fields.items() if v != fields[k]
                }
                actual_changes = {c.field: (c.before, c.after) for c in event.changes}
                if actual_changes != expected_changes:
                    raise ValueError("Interaction attempted unapproved numeric changes")
                interactive = record.after
                if historical_catalog and record.before.version == "interactive-world-4":
                    from rpg_vkr.domain.npc_reactions import react

                    historical_catalog = react(historical_catalog, record, event.turn_index)
            elif interactive:
                if physical(interactive):
                    prior_world = WorldState.from_dict(
                        {k: fields["world." + k] for k in asdict(WorldState())}
                    )
                    next_fields = fields | {c.field: c.after for c in event.changes}
                    next_world = WorldState.from_dict(
                        {k: next_fields["world." + k] for k in asdict(WorldState())}
                    )
                    interactive = reconcile(
                        interactive, prior_world, next_world, event.turn_index, historical_catalog
                    )
                for change in event.changes:
                    if change.field == "world.location":
                        interactive = replace(interactive, current=change.after)
            if turn.challenge:
                record = turn.challenge
                expected_score = fields["hero." + record.check.ability]
                if historical_gameplay:
                    from rpg_vkr.domain.gameplay import effective_character

                    hero = Character.from_dict(
                        {k: fields["hero." + k] for k in asdict(Character())}
                    )
                    if version >= 28:
                        from rpg_vkr.domain.content_v5 import inherited

                        hero = inherited(hero, historical_gameplay)
                    expected_score = effective_character(historical_gameplay, hero).score(
                        record.check.ability
                    )
                if (
                    fields["world.hp"] <= 0
                    or fields["combat.active"] is not None
                    or record.location != fields["world.location"]
                    or record.check.score != expected_score
                    or event.changes
                ):
                    raise ValueError("Challenge does not match historical state")
            if turn.scene:
                if (
                    interactive
                    and turn.scene.proposal.focus_id
                    and not any(
                        a.id == turn.scene.proposal.focus_id and a.place == interactive.current
                        for a in interactive.actor_refs
                    )
                ):
                    raise ValueError("Scene addresses an absent actor")
                historical_combat = CombatState.from_dict(
                    {
                        "actors": [
                            {
                                "id": key,
                                "hp": fields[f"actor.{key}.hp"],
                                "disposition": fields[f"actor.{key}.disposition"],
                            }
                            for key in ACTORS
                        ],
                        **{
                            key: fields["combat." + key] for key in ("active", "surprise", "rounds")
                        },
                    }
                )
                validate_scene(
                    turn.scene,
                    session.turns[: event.turn_index - 1],
                    fields["world.location"],
                    historical_combat,
                    fields["world.hp"],
                    scene=interactive or InteractiveWorld.initial(fields["world.location"]),
                    catalog=historical_catalog,
                )
                if event.changes:
                    raise ValueError("Narrative scene attempted a mechanical change")
            if turn.inspection:
                record = turn.inspection
                if (
                    fields["world.hp"] <= 0
                    or fields["combat.active"] is not None
                    or record.location != fields["world.location"]
                    or record.route_known_before != fields["world.market_known"]
                    or any(
                        item.check.score != fields["hero." + item.check.ability]
                        for item in record.checks
                    )
                ):
                    raise ValueError("Inspection does not match historical context")
                expected = [("world.market_known", False, True)] if record.reveals_route else []
                if [
                    (change.field, change.before, change.after) for change in event.changes
                ] != expected:
                    raise ValueError("Inspection attempted unapproved world changes")
            for change in event.changes:
                fields[change.field] = change.after
            if turn.gameplay and turn.gameplay["command"] == "advance":
                from rpg_vkr.gameplay_session import validate_history

                if (turn.intent or turn.action).casefold().strip().startswith("идти ") and not any(
                    c.field == "world.location" for c in event.changes
                ):
                    raise ValueError("Заблокированное перемещение не расходует время.")

                next_fields, interactive, historical_catalog = validate_history(
                    turn.gameplay,
                    fields,
                    interactive,
                    historical_catalog,
                    event.turn_index,
                    session.turns,
                )
                if version < 25 and next_fields != fields:
                    raise ValueError("Часы изменили неподтверждённые ресурсы.")
                if version >= 25:
                    expected = {
                        k: (before_fields[k], v)
                        for k, v in next_fields.items()
                        if before_fields[k] != v
                    }
                    if {c.field: (c.before, c.after) for c in original_event.changes} != expected:
                        raise ValueError(
                            "Ресурсы уровня не соответствуют подтверждённому действию."
                        )
                    fields = next_fields
                historical_gameplay = turn.gameplay["result"]["state"]
        stored_interactive = data.get("interactive_world")
        if (
            version < 20
            and stored_interactive
            and stored_interactive.get("version") == "interactive-world-3"
        ):
            raise ValueError("Physical resources require session schema 20")
        if (interactive.to_dict() if interactive else None) != (
            InteractiveWorld.from_dict(stored_interactive).to_dict() if stored_interactive else None
        ):
            raise ValueError("Final objects do not match recorded transactions")
        session.interactive_world = interactive
        if canonical(historical_catalog.to_dict() if historical_catalog else None) != canonical(
            session.catalog.to_dict() if session.catalog else None
        ):
            raise ValueError("История состояний каталога не совпадает с записями.")
        if session.chronicle:
            if any(
                e.turn > len(session.turns)
                for e in (*session.chronicle.diary, *session.chronicle.memories)
            ):
                raise ValueError("Запись хроники находится в будущем.")
        if interactive:
            validate_balances(interactive, session.world)
        stored_catalog = data.get("catalog")
        if (session.catalog.to_dict() if session.catalog else None) != (
            Catalog.from_dict(stored_catalog).to_dict() if stored_catalog is not None else None
        ):
            raise ValueError("Final catalog does not match registration history")
        if version >= 7:
            notes = data["narrations"]
            if not isinstance(notes, list) or len(notes) > len(session.turns) + 1:
                raise ValueError("Invalid narration list")
            previous = -1
            for item in notes:
                note = Narration.from_dict(item)
                if not previous < note.turn_index <= len(session.turns):
                    raise ValueError("Invalid narration order")
                if note.turn_index == len(session.turns):
                    from rpg_vkr.narrative.context import build_frame

                    if note.context_hash != build_frame(session).fingerprint:
                        raise ValueError("Saved narration does not match current scene")
                session._validate_segments(note)
                session._narrations.append(note)
                previous = note.turn_index
        from rpg_vkr.domain.campaign_progress import validate_progress

        validate_progress(session._d20_progress, session.turns)
        if version >= 24:
            from rpg_vkr.domain.gameplay import ensure_names

            ensure_names(session._gameplay["state"], session.catalog)
        if version >= 24 and canonical(session._gameplay) != canonical(data["gameplay"]):
            raise ValueError("Итог новых игровых правил не совпадает с журналом.")
        return session


from rpg_vkr.storage.migration import instrument as _instrument_copies  # noqa: E402

_instrument_copies(Session)
