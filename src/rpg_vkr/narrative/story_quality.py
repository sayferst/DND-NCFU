"""Grounded contradiction checks; literary preferences are non-blocking warnings."""

import re
from difflib import SequenceMatcher

from rpg_vkr.narrative.failures import NarrativeConflict


def spoken(text):
    matches = re.findall(r"«([^»]+)»|(?:^|\n)\s*—\s*([^\n]+)", text)
    return " ".join(quoted or dash for quoted, dash in matches).strip()


def prose_only(text):
    return re.sub(r"«[^»]*»|(?:^|\n)\s*—[^\n]*", "", text)


def words(text):
    return re.findall(r"[а-яё]+", text.casefold().replace("ё", "е"))


def quality_warnings(text, player_text, *, brief=None, previous=()):
    warnings = []
    brief = brief or {}
    if brief.get("clarification"):
        warnings.append("ambiguous_addressee")
    if brief.get("mode") == "dialogue" and not spoken(text):
        warnings.append("indirect_npc_response")
    current = words(text)
    if not re.search(r"повтор|напомн|еще раз", player_text.casefold()):
        for old in list(previous)[-3:]:
            old_words = words(old.get("result", old.get("confirmed_result", "")))
            if (
                len(current) >= 12
                and len(old_words) >= 12
                and SequenceMatcher(None, current, old_words, autojunk=False).ratio() >= 0.72
            ):
                warnings.append("similar_to_previous")
    sentences = [words(part) for part in re.split(r"[.!?\n]+", text)]
    long = [tuple(part) for part in sentences if len(part) >= 7]
    if len(set(long)) != len(long):
        warnings.append("repeat_in_answer")
    return tuple(dict.fromkeys(warnings))


def unsupported_numeric_claim(prose):
    """Require an actual resource/attribute claim, not a verb such as 'received'."""
    number = (
        r"(?:\d+|сто|тысяч\w*|семьдесят|пятьдесят|двадцать|десять|"
        r"пятнадцать|двести|триста|миллион\w*)"
    )
    resource = r"(?:золот\w*|монет\w*|опыт\w*|очк\w*|здоров\w*|сил\w*|ловкост\w*|интеллект\w*)"
    return bool(
        re.search(
            r"\bвы\s+(?:получ\w*|нашли|потеря\w*|потрат\w*|добав\w*|увелич\w*|подня\w*)[^.!?\n]{0,90}"
            + number
            + r"\s+"
            + resource
            + r"|(?:ваш\w* (?:кошел\w*|здоров\w*|сил\w*|опыт\w*|интеллект\w*)|"
            r"в (?:вашем )?кошельке)[^.!?\n]{0,80}" + number + r"\s+" + resource,
            prose,
            re.I,
        )
    )


def numeric_claim_matches_receipt(prose, receipt, balances=None):
    """A completed roll never authorizes an unrelated resource reward."""
    changes = {c["field"]: c for c in receipt.get("resource_changes", [])}
    units = {
        "золот": "world.gold",
        "монет": "world.gold",
        "опыт": "progress.xp",
        "здоров": "world.hp",
        "сил": "hero.strength",
        "ловкост": "hero.dexterity",
        "интеллект": "hero.intelligence",
    }
    numbers = {
        "сто": 100,
        "десять": 10,
        "двадцать": 20,
        "пятьдесят": 50,
        "семьдесят": 70,
        "пятнадцать": 15,
        "двести": 200,
        "триста": 300,
    }
    claims = re.findall(
        r"\bвы\s+(получ\w*|нашли|потеря\w*|потрат\w*|добав\w*|увелич\w*|подня\w*)"
        r"[^.!?\n]{0,90}?([0-9]+|сто|десять|двадцать|пятьдесят|семьдесят|пятнадцать|двести|триста)"
        r"\s+(золот|монет|опыт|здоров|сил|ловкост|интеллект)\w*",
        prose,
        re.I,
    )
    balances = balances or {}
    wallet = re.findall(
        r"в (?:вашем )?кошельке[^.!?\n]{0,50}?(\d+|сто|десять|двадцать|семьдесят)"
        r"\s+(?:золот|монет)\w*",
        prose,
        re.I,
    )
    for number in wallet:
        amount = int(number) if number.isdigit() else numbers[number.casefold()]
        if balances.get("world.gold") != amount:
            return False
    if not claims and not wallet:
        return False
    for verb, number, unit in claims:
        change = changes.get(units[unit.casefold()])
        amount = int(number) if number.isdigit() else numbers[number.casefold()]
        direction = -1 if verb.casefold().startswith(("потер", "потрат")) else 1
        if not change or change["after"] - change["before"] != direction * amount:
            return False
    return True


def check_story_quality(text, frame, player_text, *, brief=None, previous=(), campaign=None):
    """Reject grounded false outcomes, not synonyms, metaphors or an NPC's refusal."""
    brief, campaign = brief or {}, campaign or {}
    prose, normal = prose_only(text), player_text.casefold().replace("ё", "е")
    issues = []
    resolution = campaign.get("resolution") or []
    receipt = campaign.get("receipt") or {}
    interaction = campaign.get("interaction_result", "")
    if unsupported_numeric_claim(prose) and not numeric_claim_matches_receipt(
        prose, receipt, campaign.get("resource_balances")
    ):
        issues.append("Рассказ назначил неподтверждённое изменение ресурсов или характеристик.")
    resources = campaign.get("current_resources", {})
    if resources.get("mp", 0) < resources.get("mp_cap", 0) and re.search(
        r"\bман[аы]\b[^.!?\n]{0,35}\b(?:полна|полны|полон|восстановлена)\b", prose, re.I
    ):
        issues.append("Мана героя не полна по текущему состоянию движка.")
    if re.search(r"\b(?:cold|fire|damage|heal|shadow|lightning)-[А-Яа-яЁё]", text, re.I):
        issues.append("В художественный текст попала метка эффекта на другом языке.")
    hero_name = frame.hero.split(",", 1)[0]
    rename = re.search(
        r"\b(?:теперь вас зовут|ваше (?:новое )?имя)\s*[:—-]?\s*([А-ЯЁ][а-яё]+)", prose, re.I
    )
    if rename and rename[1].casefold() != hero_name.casefold():
        issues.append("Имя героя нельзя изменить художественным ответом.")
    # A transfer must have an engine receipt, independently of the writer's wording.
    if not receipt.get("committed") and re.search(
        r"(?:вам|герою)\s+(?:вруча\w*|переда\w*|отда\w*)[^.!?\n]{0,60}(?:ключ\w*|монет\w*|меч\w*|предмет\w*)|"
        r"клад\w*\s+вам\s+в\s+ладон\w*",
        prose,
        re.I,
    ):
        issues.append("Передача предмета не подтверждена движком.")
    # Preserve player agency. Requested conduct and faithful quotation are allowed.
    evidence = {
        r"\bвы\s+(?:вдруг\s+)?(?:замолч\w*|молч\w*)": r"молч|тишин|не говоря",
        r"\bвы\s+(?:вдруг\s+)?(?:реш\w*|соглас\w*|соглаш\w*|отказ\w*)": (
            r"реш|соглас|соглаш|отказ|не буду|не хочу"
        ),
        r"\bвы\s+(?:вдруг\s+)?(?:влюб\w*|боите\w*)": r"люб|бою|страх",
        r"\bвы\s+чувству\w*[^.!?\n]{0,60}(?:любов\w*|нежност\w*|страх\w*|вину)": (
            r"чувств|люб|бою|страх|вин"
        ),
    }
    for pattern, requested in evidence.items():
        if re.search(pattern, prose, re.I) and not re.search(requested, normal):
            issues.append(
                "Мастер придумал мысли, чувства, молчание или решение героя. Оставь выбор игроку."
            )
    # Mentioning consent (including a question or refusal) is not affirmative consent.
    # Check each asserted commitment separately; permission from an item owner is not
    # a promise made by the hero. This never applies any game effect.
    commitments = (
        (
            r"\bвы\s+(?:реш\w*\s+)?(?:соглас|соглаш)\w*",
            r"\b(?:я\s+)?(?:соглашаюсь|согласен|согласна)\b",
        ),
        (r"\bвы\s+[^.!?\n]{0,90}\bобеща(?:ли|ете)\b", r"\b(?:я\s+)?обещаю\b"),
    )
    for asserted, affirmation in commitments:
        claim = re.search(asserted, prose, re.I)
        if claim and not re.search(r"\bне\s+обеща(?:ли|ете)\b", claim[0], re.I):
            explicit = re.search(affirmation, normal)
            if not explicit or re.search(r"\bне\s*$", normal[: explicit.start()]) or "?" in normal:
                issues.append("Утверждение о согласии или обещании героя не подтверждено игроком.")
    invented_speech = re.search(
        r"«([^»]+)»[\s,—–-]*(?:произносите|отвечаете|говорите|спрашиваете|предлагаете)\s+вы\b",
        text,
        re.I,
    )
    if invented_speech and " ".join(words(invented_speech[1])) not in " ".join(words(player_text)):
        issues.append("Модель сочинила реплику за игрока.")
    if re.search(r"\bвы\s+(?:произносите|отвечаете|говорите|спрашиваете)\s*[:,—]\s*«", text, re.I):
        quote = spoken(text)
        if " ".join(words(quote)) not in " ".join(words(player_text)):
            issues.append("Модель сочинила реплику за игрока.")
    owned = frame.inventory.casefold()
    for item in ("нож", "кинжал", "меч", "топор", "лук", "арбалет", "посох"):
        if not re.search(r"\b" + item, owned) and re.search(
            r"(?:ваш\w* (?:пояс\w*|рук\w*|сумк\w*)|при вас|у вас)[^.!?\n]{0,70}\b" + item + r"\w*",
            prose,
            re.I,
        ):
            issues.append("Неподтверждённое снаряжение героя: " + item)
    if re.search(r"(?mi)^\s*(?:…|\.{3})?\s*(?:(?:нет|да)[,:]\s*)?я\b|^\s*(?:вы|игрок)\s*:", prose):
        issues.append("Модель сочинила неатрибутированную реплику за игрока.")
    if re.search(r"\bвы не можете.{0,50}(?:убить|напасть).{0,25}без причин", prose, re.I):
        issues.append("Не запрещай намерение по моральным причинам; исход определяет движок.")
    if not receipt.get("committed"):
        from rpg_vkr.narrative.turn_brief import mentioned_actors

        objects = campaign.get("objects", [])
        if (
            objects
            and mentioned_actors(prose, objects)
            and re.search(
                r"\bвы\s+(?:бер[её]те|забираете|взяли|забрали|выбросили|передали)\b", prose, re.I
            )
        ):
            issues.append("Неподтверждённый перенос зарегистрированного предмета.")
    # A known actor cannot reappear after the hero leaves their place.
    from rpg_vkr.domain.combat import ACTORS

    roster = campaign.get("validation_roster") or [
        {
            "name": actor[0],
            "here": any(a.startswith(actor[0] + ":") for a in frame.visible_actors),
            "alive": True,
        }
        for actor in ACTORS.values()
    ]
    for actor in roster:
        if actor["here"] and actor["alive"]:
            continue
        name = actor["name"]
        if re.search(
            r"\b" + re.escape(name) + r"\s+(?:говорит|отвечает|поднимает голову|смотрит на вас)\b",
            prose,
            re.I,
        ):
            issues.append("Собеседника нет рядом либо он выбыл; прямой разговор не подтверждён.")
    # Counts are compared to the actual roster instead of always assuming one guard.
    for name in {a.split(":", 1)[0].split()[0] for a in frame.visible_actors}:
        count = sum(a.split(":", 1)[0].split()[0] == name for a in frame.visible_actors)
        match = re.search(
            r"\b(два|двое|три|трое|четыре)\s+" + re.escape(name.rstrip("ая")) + r"\w*", prose, re.I
        )
        if (
            match
            and {"два": 2, "двое": 2, "три": 3, "трое": 3, "четыре": 4}[match[1].casefold()] > count
        ):
            issues.append(
                f"Количество существ ({name}) не совпадает с реестром: подтверждено {count}."
            )
    # Death checks bind a named actor, so 'dead leaves/silence' are not casualties.
    alive_names = [a.split(":", 1)[0] for a in frame.visible_actors if ": погиб" not in a]
    dead_names = [a.split(":", 1)[0] for a in frame.visible_actors if ": погиб" in a]
    for name in dead_names:
        root = re.escape(name[:-1] if name[-1:] in "аяйь" else name)
        if re.search(r"\b" + root + r"\w*\s+(?:говорит|отвечает|встаёт|встает|бежит)", prose, re.I):
            issues.append("Погибший персонаж не может действовать без подтверждённого эффекта.")
    if not campaign.get("death_confirmed"):
        for name in alive_names:
            root = re.escape(name[:-1] if name[-1:] in "аяйь" else name)
            if re.search(r"\b" + root + r"\w*\s+(?:погиб\w*|умер\w*|мертв\w*)", prose, re.I):
                issues.append("Смерть этого персонажа не подтверждена движком.")
    if not resolution and re.search(
        r"\bвы\s+(?:убили|убиваете|зарезали|вонзили|вонзаете|нанесли удар|наносите удар)\b",
        prose,
        re.I,
    ):
        issues.append("Сначала нужен расчёт атаки движком.")
    team = campaign.get("team_combat")
    if team:
        if team["active"] and re.search(r"\bсхватка завершена\b", prose, re.I):
            issues.append("В групповой схватке ещё есть действующие противники.")
        for actor in team["actors"]:
            root = re.escape(actor["name"])
            if actor["hp"] > 0 and re.search(
                r"\b" + root + r"\s+(?:повержен\w*|падает без сознания|погиб\w*)", prose, re.I
            ):
                issues.append("Выбытие названного участника не подтверждено движком.")
        hero_hits = [a for a in team["attacks"] if a["actor_id"] == "hero"]
        if (
            hero_hits
            and not any(a["hit"] for a in hero_hits)
            and re.search(
                r"\b(?:ваш удар (?:достигает|попадает)|вы (?:попали|вонзаете|наносите рану))\b",
                prose,
                re.I,
            )
        ):
            issues.append("По расчёту герой промахнулся; попадание не подтверждено.")
    if resolution and not team:
        last = resolution[-1]
        if not last.get("rolled") and re.search(
            r"\b(?:вонзаете|вонзили|удар достигает|попали|наносите удар)\b", prose, re.I
        ):
            issues.append("Действие заблокировано до броска; атака не выполнена.")
        if last.get("hit") is False and re.search(
            r"\b(?:удар (?:достигает|попадает)|вонзаете|наносите ран\w*|попали)\b", prose, re.I
        ):
            issues.append("По расчёту промах; попадание не подтверждено.")
        if not last.get("defeated") and re.search(
            r"\b(?:повержен\w*|падает без сознания|схватка завершена)\b", prose, re.I
        ):
            issues.append("Противник ещё не повержен.")
    if "не удалось" in interaction:
        if re.search(r"\bвы\s+(?:взяли|забрали|бер[её]те|забираете)\b", prose, re.I):
            issues.append("Попытка не удалась: передача не могла дать предмет герою.")
        # Travel is governed by per-step receipts; old atomic failures still have no prefix.
        moves = [step for step in receipt.get("steps", []) if step["operation"] == "move"]
        if (
            moves
            and not any(step["status"] == "completed" for step in moves)
            and re.search(r"\bвы\s+(?:убежали|ушли|уходите|убегаете)\b", prose, re.I)
        ):
            issues.append("Неудачная цепочка не подтвердила переход.")
    if issues:
        raise NarrativeConflict("; ".join(dict.fromkeys(issues)))
    return quality_warnings(text, player_text, brief=brief, previous=previous)
