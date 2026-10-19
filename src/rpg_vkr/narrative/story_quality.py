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
    # Quotation marks do not turn the hero's invented reply into NPC speech.
    if re.search(
        r"»[\s,—–-]*(?:произносите|отвечаете|говорите|спрашиваете|предлагаете)\s+вы\b",
        text,
        re.I,
    ) or re.search(
        r"\bвы\s+(?:произносите|отвечаете|говорите|спрашиваете)\s*[:,—]\s*«", text, re.I
    ):
        issues.append("Модель сочинила реплику за игрока. Не пиши слова героя.")
    speaker = brief.get("target_id", "")
    for actor, root in (
        ("guard", "стражник"),
        ("villager", "жительница"),
        ("merchant", "торговец"),
    ):
        from rpg_vkr.domain.combat import ACTORS

        if not any(a.startswith(ACTORS[actor][0]) for a in frame.visible_actors) and re.search(
            r"\b" + root + r"\s+(?:стоит рядом|сидит рядом|протягивает|поднимает голову|"
            r"отвечает|говорит|смотрит на вас)\b",
            text,
            re.I,
        ):
            issues.append(
                "Этого персонажа нет рядом с героем. Не возвращай прежний разговор в новую сцену."
            )
        if (
            speaker
            and actor != speaker
            and (
                re.search(
                    r"\b" + root + r"\s+(?:говорит|спрашивает|отвечает|восклицает)\s*[:—,]?\s*«",
                    text,
                    re.I,
                )
                or re.search(
                    r"»\s*[,—–-]*\s*(?:говорит|спрашивает|отвечает|восклицает)\s+" + root + r"\b",
                    text,
                    re.I,
                )
            )
        ):
            issues.append(
                "Реплика другого NPC приписана выбранному собеседнику. "
                "В этом ходе говорит только он."
            )
    if re.search(r"\b(?:два|двое|двух|три|трое|оба)\s+стражник\w*", prose, re.I):
        issues.append("В сцене один стражник. Не добавляй второго персонажа.")
    if re.search(r"\bвы не можете.{0,50}(?:убить|напасть).{0,25}без причин", prose, re.I):
        issues.append(
            "Не запрещай намерение игрока по моральным причинам: исход определяет движок."
        )
    resolution = (campaign or {}).get("resolution", ())
    interaction = (campaign or {}).get("interaction_result", "")
    if "не удалось" in interaction and re.search(
        r"\bвы\s+(?:бер[её]те|взяли|забираете|забрали|убегаете|убежали|уходите|ушли)\b",
        prose,
        re.I,
    ):
        issues.append(
            "Попытка не удалась. Не описывай получение вещи или уход как свершившийся факт."
        )
    if re.search(r"\b(?:убит[аы]?|умер\w*|мертв\w*|труп\w*|погиб\w*)\b", prose, re.I):
        issues.append("Смерть персонажа игровыми правилами не подтверждена. Не объявляй смерть.")
    if not resolution and re.search(
        r"\b(?:вы\s+)?(?:вонзаете|вонзили|добиваете|убиваете|зарезали|убили|"
        r"наносите удар|нанесли удар)\b",
        prose,
        re.I,
    ):
        issues.append(
            "Сначала нужен расчёт атаки движком. Не назначай боевой исход в свободной сцене."
        )
    if resolution:
        last = resolution[-1]
        if not last.get("rolled") and re.search(
            r"\b(?:вонзаете|вонзили|удар достигает|попали|наносите удар)\b", prose, re.I
        ):
            issues.append("Действие заблокировано до броска. Не описывай выполненную атаку.")
        if re.search(r"\b(?:обыскиваете|обыскали|забираете|забрали)\b", prose, re.I):
            issues.append(
                "Обыск и получение добычи не выполнены движком. Не добавляй их в рассказ."
            )
        if last.get("hit") is False and re.search(
            r"\b(?:удар (?:достигает|попадает)|вонзаете|наносите ран\w*|попали)\b", prose, re.I
        ):
            issues.append("По расчёту промах. Не описывай попадание или ранение от этого удара.")
        if not last.get("defeated") and re.search(
            r"\b(?:повержен\w*|падает без сознания|схватка завершена)\b", prose, re.I
        ):
            issues.append("Противник ещё не повержен. Продолжение боя нельзя заменить победой.")
        if last.get("defeated") and re.search(
            r"\b(?:стражник|жительница|торговец)\s+(?:атакует|отвечает ударом|бьет|наносит удар)\b",
            prose,
            re.I,
        ):
            issues.append("Поверженный противник не наносит новую ответную атаку.")
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
