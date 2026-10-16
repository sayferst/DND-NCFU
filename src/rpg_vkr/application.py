"""Session state and command routing; narration never performs dice calculations."""

from dataclasses import asdict, dataclass, replace

from rpg_vkr.commands import normalise_action
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
from rpg_vkr.domain.progression import (
    ARCHETYPES,
    PRACTICE_COMMANDS,
    HeroProgress,
    describe_award,
    describe_progress,
)
from rpg_vkr.domain.world import WORLD_COMMANDS, WorldState, perform_action
from rpg_vkr.narrative.offline import INTRODUCTION, respond

ROLL_COMMANDS = {"бросить d20", "бросить д20"}
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
    ) -> None:
        self.dice = DiceRoller(seed)
        self.character = Character() if character is None else character
        self.world = WorldState() if world is None else world
        self.progress = HeroProgress() if progress is None else progress
        if self.progress.enabled and self.progress.character() != self.character:
            raise ValueError("Character does not match development history")
        self.combat = CombatState() if combat is None else combat
        self.introduction = INTRODUCTION
        self._turns: list[Turn] = []

    @classmethod
    def create_hero(cls, character: Character, class_id: str, seed: int | None = None):
        progress = HeroProgress(class_id, character)
        kit = ARCHETYPES[class_id]
        return cls(
            seed=seed,
            character=character,
            world=WorldState(gold=kit.gold, bandages=kit.bandages),
            progress=progress,
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

    def submit(self, action: str) -> Turn:
        action = _text(action, 500).strip()
        if len(self._turns) >= MAX_TURNS:
            raise ValueError("Достигнут предел в 2000 действий. Сохраните сессию.")
        command = normalise_action(action)
        checkpoint = self.dice.checkpoint()
        try:
            turn, world = self._resolve_turn(action, command)
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
        except Exception:
            self.dice.restore(checkpoint)
            raise
        self.world = world
        self.combat = combat
        self.progress = progress
        self.character = character
        self._turns.append(turn)
        return turn

    def _resolve_turn(self, action: str, command: str) -> tuple[Turn, WorldState]:
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
        information = {"состояние", "инвентарь", "задание", "развитие", "помощь", "осмотреться"}
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
        if command in PRACTICE_COMMANDS:
            return self._practice(action, command)
        if command in WORLD_COMMANDS:
            outcome = perform_action(self.world, command, self.character, self.dice)
            text = outcome.text
            if command in {"осмотреться", "осмотреть деревню", "я осматриваюсь"}:
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
            "Изменить персонажа", "Система", f"Профиль изменён: {character.name}. {summary}."
        )
        self.character = character
        self._turns.append(turn)
        return True

    def to_dict(self) -> dict:
        return {
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
    def from_dict(cls, data: object, version: int = 6) -> "Session":
        if type(version) is not int or version not in (1, 2, 3, 4, 5, 6):
            raise ValueError("Unsupported session version")
        keys = {"seed", "introduction", "turns"}
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
        session.introduction = _text(data["introduction"], 4000)
        turns = data["turns"]
        if not isinstance(turns, list) or len(turns) > MAX_TURNS:
            raise ValueError("Invalid turn history")
        for item in turns:
            turn_keys = {"action", "speaker", "text", "roll"}
            if version >= 2:
                turn_keys.add("check")
            if version >= 6:
                turn_keys.update({"actor_id", "combat"})
            if not isinstance(item, dict) or set(item) != turn_keys:
                raise ValueError("Invalid turn")
            action = _text(item["action"], 500)
            text = _text(item["text"], 4000)
            roll = None
            check = None
            stored_check = item.get("check")
            if version >= 6 and item["combat"] is not None:
                previous_record = next(
                    (turn.combat for turn in reversed(session._turns) if turn.combat), None
                )
                record = restore_record(
                    item["combat"], normalise_action(action), session.combat, session.dice
                )
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
                        and normalise_action(action)
                        in (
                            {"исследовать дорогу"}
                            | ({"помочь разгрузить телегу"} if version >= 5 else set())
                        )
                        and item["speaker"] == "Мир"
                        and stored_check["ability"]
                        == (
                            "dexterity"
                            if normalise_action(action) == "исследовать дорогу"
                            else "strength"
                        )
                        and stored_check["difficulty"] == 10
                    )
                    if (
                        CHECK_COMMANDS.get(normalise_action(action)) != stored_check["ability"]
                        and not world_check
                    ):
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
                    normalise_action(action) not in ROLL_COMMANDS
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
                        and normalise_action(action)
                        in (WORLD_COMMANDS | (PRACTICE_COMMANDS if version >= 5 else set()))
                    )
                    or (
                        version >= 3
                        and item["speaker"] == "Система"
                        and (
                            action == "Изменить персонажа"
                            or (version >= 5 and normalise_action(action) == "развитие")
                        )
                    )
                )
                if version >= 5 and item["speaker"] in NPC_SPEAKERS:
                    valid_speaker = normalise_action(action) in WORLD_COMMANDS and text.startswith(
                        item["speaker"] + ":"
                    )
                if stored_check is not None or not valid_speaker:
                    raise ValueError("Invalid narration turn")
            actor_id = item.get("actor_id", NAMES_TO_IDS.get(item["speaker"]))
            if version >= 6 and actor_id != NAMES_TO_IDS.get(item["speaker"]):
                raise ValueError("Missing or changed actor identity")
            if actor_id is not None and (
                actor_id not in ACTORS or ACTORS[actor_id][0] != item["speaker"]
            ):
                raise ValueError("Actor identity mismatch")
            session._turns.append(Turn(action, item["speaker"], text, roll, check, actor_id))
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
                        normalise_action(turn.action)
                        in {"исследовать дорогу", "помочь разгрузить телегу"}
                        and turn.check is not None
                    )
                    or (
                        normalise_action(turn.action) == "изучить учебник"
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
        return session
