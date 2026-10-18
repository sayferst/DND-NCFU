"""Topic-aware authored grounding and small replayable social reactions for three NPCs."""

import re

from rpg_vkr.commands import normalise_action
from rpg_vkr.domain.combat import ACTORS
from rpg_vkr.domain.social import DialogueRecord, grievance, grievance_after
from rpg_vkr.narrative.speech import explicit_target, speech_details, unquoted

ADDRESSEES = {"жительница": "villager", "стражник": "guard", "торговец": "merchant"}
QUESTIONS = {
    "чем занята",
    "яем занята",
    "чем занят",
    "чем занимаешься",
    "что случилось",
    "чем могу помочь",
    "как пройти на рынок",
    "где рынок",
    "что продаешь",
    "что у тебя есть",
    "сколько стоит бинт",
    "что ты тут делаешь",
    "что вы тут делаете",
}
VOICES = {
    "villager": "Простая, прямая речь занятого человека, без загадок и высокопарности.",
    "guard": "Короткие спокойные ответы о дороге и порядке, без угроз без причины.",
    "merchant": "Деловая речь о предложении и условиях, без навязывания покупки.",
}
GOALS = {
    "villager": "Закончить сборы на рынок и получить помощь без унижения.",
    "guard": "Наблюдать за дорогой и поддерживать порядок у ворот.",
    "merchant": "Вести обмен на оговорённых условиях и без угроз.",
}


def dialogue_intent(action):
    """Finite offline phrases; never accept a compound action by a matching keyword."""
    text = unquoted(action)
    if re.search(r"\sи\s|;|\n|[?!].+\w", text):
        return None
    target = explicit_target(action)
    match = re.fullmatch(r"(жительница|стражник|торговец)\s*[:,]\s*(.+)", text)
    if match:
        text = match[2]
    text = re.sub(r"^(привет|здравствуй|здравствуйте)(?:\s*[,!.?]\s*|\s+|$)", "", text)
    if not text and action.strip(".!? \t\n"):
        return target, "greeting"
    act, topic = speech_details(action)
    if text in QUESTIONS:
        return target or ("villager" if text in {"чем занята", "яем занята"} else None), topic
    if act in {"insult", "threat", "apology", "refusal", "contact"}:
        return target, topic
    if (
        re.fullmatch(
            r"(?:я )?(?:спрашиваю|спросить|спрошу)(?: у)? .{1,30},? "
            r"(?:что|чем|нужна ли).{1,45}",
            text,
        )
        and target
    ):
        return target, topic
    return None


def last_interlocutor(session):
    for turn in reversed(session.turns):
        if normalise_action(turn.intent or turn.action) in {
            "идти к воротам",
            "идти на дорогу",
            "идти на рынок",
        }:
            break
        if (
            turn.actor_id in ADDRESSEES.values()
            and ACTORS[turn.actor_id][1] == session.world.location
        ):
            return turn.actor_id
    return None


def activity(session, target):
    if target == "guard":
        return "наблюдает за дорогой у деревенских ворот"
    if target == "merchant":
        return "торгует у своего прилавка на рынке"
    if session.world.quest == "active":
        return "ждёт доставки переданной вам корзины на рынок"
    if session.world.quest == "completed":
        return "занимается своими сборами; доставка корзины уже завершена"
    helped = any(
        normalise_action(t.intent or t.action)
        in {"помочь", "помочь жительнице", "помочь собрать яблоки"}
        and t.text.startswith("Вы помогаете собрать яблоки")
        for t in session.turns
    )
    return (
        "собрала яблоки с вашей помощью и собирается на рынок"
        if helped
        else "собирает рассыпавшиеся яблоки из опрокинувшейся корзины"
    )


def _answer(session, target, topic):
    if topic == "occupation":
        return {
            "villager": (
                "Жду, когда вы доставите корзину на рынок."
                if session.world.quest == "active"
                else "Спасибо, доставка завершена. Собираюсь по своим делам."
                if session.world.quest == "completed"
                else "Яблоки уже собраны с вашей помощью. Теперь собираюсь на рынок."
                if activity(session, target).startswith("собрала")
                else "Яблоки собираю. Корзина перевернулась у ворот, а мне ещё на рынок успеть."
            ),
            "guard": "Караулю дорогу. Слежу, чтобы у ворот был порядок.",
            "merchant": "Торгую. Если интересует товар, можем обсудить его у прилавка.",
        }[target]
    if topic == "directions":
        return "Рынок за площадью. Если собираетесь туда, я могу объяснить дорогу."
    if topic == "greeting":
        return {
            "villager": "Здравствуйте. Вы что-то хотели?",
            "guard": "Здравствуй. Что привело к воротам?",
            "merchant": "Добрый день. Чем интересуетесь?",
        }[target]
    if target == "villager" and topic == "help":
        return {
            "available": "Нужно доставить корзину на рынок. Заплачу 5 золотых. Возьмётесь?",
            "active": "Вы уже взяли мою корзину. Её ждут на рынке.",
            "completed": "Спасибо за доставку. Новых поручений у меня пока нет.",
        }[session.world.quest]
    if target == "merchant" and topic in {"wares", "help"}:
        if not session.world.trading:
            return "Подойдите к прилавку, тогда покажу, что есть в продаже."
        from rpg_vkr.domain.world import perform_action

        offer = perform_action(session.world, "торговля", session.character, session.dice).text
        return (
            offer.removeprefix("Торговец: ")
            .split("Команды:", 1)[0]
            .replace("«", "")
            .replace("»", "")
            .strip()
        )
    return {
        "villager": "Что именно вы хотите узнать?",
        "guard": "Спросите прямо. Вас интересует дорога или порядок у ворот?",
        "merchant": "Что вас интересует: товар или условия сделки?",
    }[target]


def resolve_conversation(session, action, target=None, *, topic_hint=None, contact=False):
    act, topic = speech_details(action)
    if contact:
        act, topic = "contact", "greeting"
    elif topic_hint and topic == "other":
        topic = topic_hint
    if target is None:
        target = last_interlocutor(session)
        if target is None:
            target = {"wares": "merchant", "directions": "guard"}.get(topic)
    if target is None or ACTORS[target][1] != session.world.location:
        return (
            "Рассказчик",
            "Уточните, к кому обращаетесь. Собеседник должен находиться рядом.",
            None,
            None,
        )
    name = ACTORS[target][0]
    actor = session.combat.actor(target)
    if actor.hp == 0 or actor.disposition == "hostile":
        return (
            name,
            f"{name}: мирное взаимодействие недоступно — "
            + ("персонаж повержен." if actor.hp == 0 else "персонаж враждебен."),
            target,
            None,
        )
    before = grievance(session.turns, target)
    record = DialogueRecord(target, act, topic, before, grievance_after(before, act))
    if act == "insult":
        line = (
            {
                "villager": "Я вас не оскорбляла. Разговаривайте со мной уважительно.",
                "guard": "Придержи язык. Здесь можно обойтись без оскорблений.",
                "merchant": "Грубостью хорошей сделки не добьёшься.",
            }[target]
            if record.after < 2
            else "После таких слов я не хочу продолжать разговор."
        )
    elif act == "threat":
        line = "Не угрожайте мне. Такой разговор я продолжать не буду."
    elif act == "apology":
        line = "Хорошо. Надеюсь, это не повторится." if before else "Между нами пока нет ссоры."
    elif before >= 2:
        line = (
            "Я ещё не готова разговаривать после ваших слов."
            if target == "villager"
            else "После ваших слов разговор пока окончен."
        )
    elif act == "refusal":
        line = (
            "Ваше право. Тогда поищу другого помощника."
            if target == "villager" and session.world.quest == "available"
            else "Хорошо. Настаивать не буду."
        )
    else:
        line = _answer(session, target, topic)
    gesture = {
        "villager": "Жительница поднимает голову.",
        "guard": "Стражник обращает на вас внимание.",
        "merchant": "Торговец прислушивается к вашим словам.",
    }[target]
    return name, f"{name}: {gesture}\n— {line}", target, record


def dialogue_reply(session, intent):
    # Compatibility for code using the previous small offline helper.
    target, topic = intent
    return resolve_conversation(session, "", target, topic_hint=topic)[:3]


def dialogue_context(session):
    if not session.turns or not session.turns[-1].dialogue:
        return None
    turn = session.turns[-1]
    record = turn.dialogue
    return {
        "speaker": ACTORS[record.target][0],
        "target_id": record.target,
        "speech_act": record.act,
        "topic": record.topic,
        "activity": activity(session, record.target),
        "voice": VOICES[record.target],
        "public_goal": GOALS[record.target],
        "approved_reply": turn.text.split("\n— ", 1)[-1],
        "reaction": "разговор прерван из-за грубости" if record.after >= 2 else "готов к разговору",
        "rule": (
            "Ответить на реплику, сохранив смысл approved_reply; не менять собеседника, "
            "не придумывать действие героя, предложение не равно согласию."
        ),
    }
