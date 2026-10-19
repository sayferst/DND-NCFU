"""Session state and command routing; narration never performs dice calculations."""

from dataclasses import asdict, dataclass, replace

from rpg_vkr.commands import CHAT_TARGETS, NPC_CONTACTS, allowed_intents, normalise_action
from rpg_vkr.domain.campaign import Campaign, NPCProfile, procedural_profile
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
from rpg_vkr.domain.meaning import Meaning
from rpg_vkr.domain.memory import WorldMemory, snapshot
from rpg_vkr.domain.progression import (
    ARCHETYPES,
    PRACTICE_COMMANDS,
    HeroProgress,
    describe_award,
    describe_progress,
)
from rpg_vkr.domain.social import DialogueRecord, grievance
from rpg_vkr.domain.world import (
    OBSERVE_COMMANDS,
    WHERE_COMMANDS,
    WORLD_COMMANDS,
    WorldState,
    perform_action,
)
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


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("Invalid session text")
    return value


class Session:
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

    @classmethod
    def create_hero(
        cls, character: Character, class_id: str, seed: int | None = None, *, description=""
    ):
        progress = HeroProgress(class_id, character)
        kit = ARCHETYPES[class_id]
        return cls(
            seed=seed,
            character=character,
            world=WorldState(gold=kit.gold, bandages=kit.bandages),
            progress=progress,
            campaign=Campaign.create(description),
        )

    @property
    def extra_items(self) -> tuple[tuple[str, str], ...]:
        if not self.progress.enabled:
            return ()
        kit = ARCHETYPES[self.progress.class_id]
        return (
            (kit.equipment, "Оружие для авторской схватки"),
            ("Дорожный учебник", "Изучить один раз для обучения Интеллекту"),
        )

    @property
    def turns(self) -> tuple[Turn, ...]:
        return tuple(self._turns)

    def submit(
        self,
        action: str,
        *,
        intent: str | None = None,
        origin="typed",
        meaning=None,
        profile=None,
        intent_source="direct",
    ) -> Turn:
        action = _text(action, 500).strip()
        if len(self._turns) >= MAX_TURNS:
            raise ValueError("Достигнут предел в 2000 действий. Сохраните сессию.")
        if intent is not None and (not isinstance(intent, str) or intent not in allowed_intents()):
            raise ValueError("Неподдерживаемое намерение. Мир не изменён.")
        if meaning is not None and not isinstance(meaning, Meaning):
            raise ValueError("Invalid semantic evidence")
        if meaning is None and intent is None:
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
        if not isinstance(origin, str) or origin not in {"typed", "quick"}:
            raise ValueError("Invalid input origin")
        binding_error = (
            validate_binding(
                action,
                command,
                location=self.world.location,
                active_target=self.combat.active,
                interlocutor=last_interlocutor(self),
            )
            if intent is not None and not (meaning and meaning.kind == "master")
            else None
        )
        if binding_error:
            command = intent = "уточнить намерение"
            meaning = None
        campaign_before = self.campaign
        if profile is not None:
            if (
                not isinstance(profile, NPCProfile)
                or not meaning
                or profile.actor_id != meaning.target
                or profile.created_at_turn != len(self.turns) + 1
                or ACTORS[profile.actor_id][1] != self.world.location
            ):
                raise ValueError("NPC proposal does not match this scene")
            candidate = self.campaign.add(profile)
        else:
            candidate = self.campaign
        if (
            meaning
            and meaning.target
            and ACTORS[meaning.target][1] == self.world.location
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
            if progress.enabled:
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
            memory = self.memory.append(turn, before, snapshot(world, character, combat, progress))
        except Exception:
            self.campaign = campaign_before
            self.dice.restore(checkpoint)
            raise
        self.memory = memory
        self.world = world
        self.combat = combat
        self.progress = progress
        self.character = character
        self._turns.append(turn)
        return turn

    def submit_scene(self, action, proposal, model, *, base_turn):
        """Commit validated fiction and its visible segments in one transaction."""
        from rpg_vkr.domain.meaning import Meaning
        from rpg_vkr.narrative.context import build_frame
        from rpg_vkr.narrative.segments import split_story
        from rpg_vkr.narrative.speech import speech_details

        action = _text(action, 500)
        record = SceneRecord(base_turn, self.world.location, model, proposal)
        validate_scene(record, self.turns, self.world.location, self.combat, self.world.hp)
        target = proposal.focus_id
        dialogue = None
        if target:
            act, topic = speech_details(action)
            if act == "contact" and "спро" in action.casefold():
                act, topic = "question", "other"
            _, _, _, dialogue = resolve_conversation(
                self, action, target, meaning=Meaning("dialogue", target, act, topic)
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
                    segments=split_story(proposal.narration, target),
                )
            )
        except Exception:
            self._turns.pop()
            self.memory = old_memory
            raise
        return turn

    def _resolve_turn(self, action: str, command: str, meaning=None) -> tuple[Turn, WorldState]:
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
                text = describe_scene(self.world)
                visible = [
                    actor
                    for actor in self.combat.actors
                    if ACTORS[actor.id][1] == self.world.location
                ]
                text += "\n" + "\n".join(
                    f"{ACTORS[actor.id][0]}: {disposition_label(actor).lower()}, "
                    f"{health_description(actor)}."
                    for actor in visible
                )
            if command == "инвентарь" and self.extra_items:
                text += "; " + "; ".join(name + " ×1" for name, _ in self.extra_items)
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
        if self.combat.active is not None or self.world.hp == 0:
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
        if len(self._turns) >= MAX_TURNS:
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

    def to_dict(self) -> dict:
        return {
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
                asdict(turn) | {"combat": turn.combat.to_dict() if turn.combat else None}
                for turn in self._turns
            ],
        }

    @classmethod
    def from_dict(cls, data: object, version: int = 12) -> "Session":
        if type(version) is not int or version not in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
            raise ValueError("Unsupported session version")
        keys = {"seed", "introduction", "turns"}
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
        session.campaign = (
            Campaign.from_dict(data["campaign"]) if version >= 10 else Campaign.migrate(data)
        )
        session.introduction = _text(data["introduction"], 4000)
        turns = data["turns"]
        if not isinstance(turns, list) or len(turns) > MAX_TURNS:
            raise ValueError("Invalid turn history")
        for item in turns:
            turn_keys = {"action", "speaker", "text", "roll"}
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
            text = _text(item["text"], 4000)
            roll = None
            check = None
            stored_check = item.get("check")
            if version >= 12 and item["scene"] is not None:
                record = SceneRecord.from_dict(item["scene"])
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
        if version >= 5:
            session.progress = HeroProgress.from_dict(data["progress"], session.turns)
            if session.progress.enabled:
                if session.progress.character() != session.character:
                    raise ValueError("Character growth does not match recorded events")
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
        for event in session.memory.events:
            turn = session.turns[event.turn_index - 1]
            if turn.scene:
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
        return session
