"""Bounded runtime checks. These heuristics are not a literary quality score."""

import re
from difflib import SequenceMatcher


def spoken(text):
    matches = re.findall(r"«([^»]+)»|(?:^|\n)\s*—\s*([^\n]+)", text)
    return " ".join(quoted or dash for quoted, dash in matches).strip()


def prose_only(text):
    return re.sub(r"«[^»]*»|(?:^|\n)\s*—[^\n]*", "", text)


def words(text):
    return re.findall(r"[а-яё]+", text.casefold().replace("ё", "е"))


def check_story_quality(text, frame, player_text, *, brief=None, previous=(), campaign=None):
    brief = brief or {}
    speech = spoken(text)
    prose = prose_only(text)
    normal = player_text.casefold().replace("ё", "е")
    issues = []
    # Do not infer a player's emotions, decisions or reply. Physical senses are allowed.
    sensory = r"(?:запах|аромат|холод|прохлад|тепл|жар|сырост|ветер|вкус|прикоснов)\w*"
    prose = re.sub(r"\b(?:вы\s+чувству\w*|чувствуя)\s+" + sensory, "", prose, flags=re.I)
    agency = {
        r"\bвы\s+(?:вдруг\s+)?(?:замолч\w*|молч\w*)": r"молч|тишин",
        r"\bвы\s+(?:вдруг\s+)?(?:реш\w*|соглас\w*|отказ\w*)": r"реш|соглас|отказ",
        r"\bвы\s+(?:вдруг\s+)?(?:чувств\w*|влюб\w*|боите\w*)": r"чувств|люб|бою|страх",
        r"\b(?:чувствуя|не зная,? что сказать)\b": r"чувств|не знаю",
        r"\bвы\s+(?:понима\w*|поня\w*|осозна\w*)": (
            r"понима|поня|осозна|чит|изуч|исслед|осмотр|осматр|узна|провер|оцен|как|почему|откуда"
        ),
    }
    for pattern, evidence in agency.items():
        if re.search(pattern, prose, re.I) and not re.search(evidence, normal):
            issues.append(
                "Мастер придумал мысли, чувства, молчание или решение героя. Оставь выбор игроку."
            )
    # Unassigned first-person lines and role labels can simulate a reply by the player.
    hero_name = frame.hero.split(",", 1)[0]
    if re.search(r"(?mi)^\s*(?:…|\.{3})?\s*(?:(?:нет|да)[,:]\s*)?я\b", prose) or re.search(
        r"(?mi)^\s*(?:игрок|вы|" + re.escape(hero_name) + r")\s*:", prose
    ):
        issues.append(
            "Модель сочинила неатрибутированную реплику за игрока. Говорит только указанный NPC."
        )
    approach = r"\bвы\s+(?:подход\w*|подош\w*|подойд\w*)"
    if len(re.findall(approach, prose, re.I)) > max(
        1, len(re.findall(r"\b(?:подойду|подойти|подхожу)\b", normal))
    ):
        issues.append("Один подход героя описан несколько раз. Оставь одно действие и реакцию NPC.")
    owned = (frame.inventory + " " + (campaign or {}).get("hero_description", "")).casefold()
    for item in ("нож", "кинжал", "меч", "топор", "лук", "арбалет", "посох"):
        if not re.search(r"\b" + item, owned) and re.search(
            r"(?:ваш\w*|у вас|при вас)[^.!?\n]{0,100}\b" + item + r"\w*", prose, re.I
        ):
            issues.append("Мастер приписал герою отсутствующее снаряжение: " + item)
    sentences = [words(s) for s in re.split(r"[.!?\n]+", text)]
    long = [s for s in sentences if len(s) >= 7]
    if len({tuple(s) for s in long}) != len(long):
        issues.append("В ответе повторяется одно и то же предложение. Напиши продолжение один раз.")
    if not re.search(r"повтор|напомн|еще раз", normal):
        current = words(text)
        for old in list(previous)[-3:]:
            old_text = old.get("result", old.get("confirmed_result", ""))
            old_words = words(old_text)
            if len(current) >= 12 and len(old_words) >= 12:
                if SequenceMatcher(None, current, old_words, autojunk=False).ratio() >= 0.72:
                    issues.append(
                        "Ответ почти повторяет предыдущий рассказ. Ответь на НОВОЕ сообщение."
                    )
                for sentence in re.split(r"[.!?\n]+", old_text):
                    old_sentence = words(sentence)
                    if len(old_sentence) >= 9 and " ".join(old_sentence) in " ".join(current):
                        issues.append(
                            "Скопировано длинное предложение из прошлого хода. Продолжи разговор."
                        )
    if brief.get("clarification"):
        issues.append("Не указан адресат: " + brief["clarification"])
    if brief.get("mode") == "dialogue":
        if not speech:
            issues.append(
                "NPC должен прямо ответить на вопрос или обращение, а не описывать пейзаж"
            )
        else:
            checks = {
                "wellbeing": (
                    r"хорош|неплох|держ|поряд|устал|тяжел|скверн|плох|бед|справ|жив|спокой|отлич|"
                    r"ничего|нормаль|прекрас|огорч|тревож|неваж|сносно|беспоко|так себе"
                ),
                "help": (
                    r"помо|помощ|справ|нужн|благодар|придерж|подерж|соб[еи]р|корзин|постав|"
                    r"не надо|не требу"
                ),
            }
            for topic in brief.get("topics", ()):
                if topic == "name":
                    if not re.search(r"\b" + re.escape(brief["public_name"]) + r"\b", speech, re.I):
                        issues.append(
                            "Не отвечено на вопрос об имени. NPC должен представиться: "
                            + brief["public_name"]
                        )
                elif topic in checks and not re.search(
                    checks[topic], speech.casefold().replace("ё", "е")
                ):
                    label = "как дела" if topic == "wellbeing" else "нужна ли помощь"
                    issues.append(
                        "Не отвечено на вопрос «" + label + "». Дай содержательный ответ NPC."
                    )
    if issues:
        raise ValueError("; ".join(dict.fromkeys(issues)))
