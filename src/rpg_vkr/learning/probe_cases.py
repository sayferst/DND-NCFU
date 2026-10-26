"""Original live-probe worlds. No external corpus text or user campaigns."""

from rpg_vkr.application import Session
from rpg_vkr.domain.adventure import build_world
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.interactions import Step, WorldPlan
from rpg_vkr.domain.progression import ARCHETYPES

PRIVATE_PLOT = "HIDDEN_CANON_Q7N9"
PRIVATE_DIARY = "PRIVATE_HERO_Z4P8"


def world():
    character = Character(
        name="Путник", **dict(zip(ABILITY_NAMES, ARCHETYPES["fighter"].scores, strict=True))
    )
    session = Session.create_hero(character, "fighter", seed=37)
    session.enable_gameplay(
        {
            "species": "human",
            "profile": "mage",
            "age": 25,
            "kit": "artisan",
            "background": "Путешественник",
            "appearance": "Дорожный плащ",
            "skills": {"arcana": 2, "smithing": 2, "alchemy": 1, "repair": 1, "survival": 1},
            "starting_spells": ["utility_1", "restoration_1"],
            "talent": "",
        },
        revision=5,
    )
    actors = (
        ("scribe", "Ливна", "square", "neutral"),
        ("distant", "Орн", "tower", "neutral"),
        ("first", "Первый налётчик", "square", "hostile"),
        ("second", "Второй налётчик", "square", "hostile"),
        ("friend", "Дозорная", "square", "friendly"),
    )
    definitions, entities = [], []
    for id, name, place, disposition in actors:
        properties = {"hp_max": 12, "strength": 8, "dexterity": 8}
        if id == "friend":
            properties["party_ally"] = True
        definitions.append(
            {
                "id": id + "_type",
                "name": name,
                "kind": "actor",
                "categories": ["npcs"],
                "properties": properties,
            }
        )
        entities.append(
            {
                "id": id,
                "definition_id": id + "_type",
                "parent_id": place,
                "state": {"hp": 12, "disposition": disposition},
            }
        )
    definitions.extend(
        [
            {
                "id": "board_type",
                "name": "Дорожная доска",
                "kind": "item",
                "categories": ["miscellaneous"],
                "properties": {"appearance": "Вырезан знак моста"},
            },
            {
                "id": "blade_type",
                "name": "Выставочный клинок",
                "kind": "item",
                "categories": ["weapons"],
                "price_cp": 100,
                "properties": {"appearance": "Прямой клинок с медной рукоятью"},
            },
        ]
    )
    entities.extend(
        [
            {"id": "board", "definition_id": "board_type", "parent_id": "square"},
            {
                "id": "blade",
                "definition_id": "blade_type",
                "parent_id": "scribe",
                "owner_id": "scribe",
            },
        ]
    )
    value = {
        "title": "Район кузницы",
        "opening": "У ворот слышен звон молотка.",
        "private_plot": PRIVATE_PLOT + ": не известный жителям замысел.",
        "hooks": ["Узнать о ремесле"],
        "start": "square",
        "definitions": definitions,
        "entities": entities,
        "places": [
            {
                "id": "square",
                "name": "Площадь у кузницы",
                "parent": "",
                "description": "У ворот стоит доска со знаком моста.",
            },
            {
                "id": "tower",
                "name": "Дальняя башня",
                "parent": "square",
                "description": "Двор скрыт за поворотом.",
            },
        ],
    }
    session.start_world(build_world(value, session, "original-live-probe"))
    session.write_diary("Личная заметка", PRIVATE_DIARY, pinned=True)
    return session


def clone(session):
    return Session.from_dict(session.to_dict(), version=session.schema_version)


def cases():
    base = world()
    result = []

    def add(id, query, session=None, obstacle=""):
        result.append(
            {
                "id": id,
                "query": query,
                "session": clone(session or base),
                "obstacle": obstacle,
                "confirmed": id
                in {"inspect", "ownership", "spell_utility", "time", "team_begin", "team_receipt"},
            }
        )

    inspected = clone(base)
    inspected.submit_interaction("Осматриваю дорожную доску", WorldPlan((Step("look", "board"),)))
    add("inspect", "Мастер, что видно на дорожной доске после осмотра?", inspected)
    inspected.submit_interaction("Осматриваю чужой клинок", WorldPlan((Step("look", "blade"),)))
    add("ownership", "Мастер, осмотрел клинок Ливны. Он всё ещё чужой?", inspected)
    add("no_purchase", "Мастер, узнаю цену клинка, но пока ничего не покупаю.")
    add("free_action", "Подставляю плащ ветру, чтобы понять, откуда тянет дым.")
    add("npc_name", "Ливна, как вас зовут?")
    add("npc_occupation", "Ливна, чем вы здесь заняты?")
    add("absent_npc", "Мастер, могу ли я сейчас поговорить с Орном из дальней башни?")
    add("npc_knowledge", "Ливна, что вам известно о замысле незнакомого вам отшельника?")
    add("hero_privacy", "Ливна, вы знаете содержание моего личного дневника?")
    add("consent", "Мастер, спрашиваю условия поручения, ещё не соглашаясь.")
    add("promise", "Мастер, я ничего не обещал и пока не решил, возьмусь ли.")
    add("metaphor", "Мастер, мёртвая тишина у башни: что слышно вокруг?")

    for id, command, args, query in (
        (
            "craft_no_material",
            "manufacture",
            {"recipe": "sword", "quality": 1},
            "Мастер, попытка выковать меч без подготовленных слитков не удалась. "
            "Объясни препятствие.",
        ),
        (
            "craft_unknown",
            "manufacture",
            {"recipe": "unknown_recipe", "quality": 1},
            "Мастер, у меня нет подтверждённого рецепта. Почему изделие ещё не создано?",
        ),
        (
            "spell_unknown",
            "cast",
            {"spell": "unknown_spell", "target": "hero"},
            "Мастер, это заклинание не изучено; опиши отсутствие выполненного эффекта.",
        ),
        (
            "spell_utility",
            "cast",
            {"spell": "utility_1", "target": "hero"},
            "Мастер, опиши подтверждённый эффект только что выполненного заклинания.",
        ),
        (
            "time",
            "wait",
            {"minutes": 120},
            "Мастер, как выглядит площадь после двух часов ожидания по календарю?",
        ),
    ):
        session = clone(base)
        before = session.to_dict(), session.dice.checkpoint()
        obstacle = ""
        try:
            session.perform_gameplay(command, args, "probe_" + id)
        except ValueError as error:
            obstacle = str(error)
            if before != (session.to_dict(), session.dice.checkpoint()):
                raise AssertionError("Неудачная операция изменила состояние.") from error
        add(id, query, session, obstacle)

    battle = clone(base)
    battle.perform_gameplay(
        "encounter", {"enemies": ["first", "second"], "allies": ["friend"]}, "probe_battle"
    )
    add("team_begin", "Мастер, кто участвует в начавшейся схватке?", battle)
    battle.perform_gameplay("attack", {"target": "first", "lethal": 0}, "probe_attack")
    add(
        "team_receipt",
        "Мастер, опиши последний удар по квитанции, не завершая бой заранее.",
        battle,
    )

    remembered = clone(inspected)
    for n in range(1, 101):
        remembered.perform_gameplay("wait", {"minutes": 1}, "probe_memory_" + str(n))
        if n in (10, 50, 100):
            add("memory_" + str(n), "Мастер, что я помню об осмотре клинка Ливны?", remembered)
    add(
        "no_reward",
        "Мастер, осмотр доски не принёс денег или опыта. Что можно делать дальше?",
        inspected,
    )
    add("no_invented_roll", "Мастер, просто смотрю на небо. Не назначай бросок без правила.")
    if len(result) != 24:
        raise AssertionError("Нужны24разных игровых сценария.")
    return result
