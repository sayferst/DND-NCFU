"""Project new XP only from confirmed rule records, never narrator prose."""

from rpg_vkr.domain.d20_progression import D20Progress


def achievements(turns):
    result = {}
    victories = set()
    for index, turn in enumerate(turns, 1):
        if turn.combat and turn.combat.outcome.victory:
            key = "victory:" + turn.combat.outcome.actor_id
            result.setdefault(key, (50, "Первая победа над противником", index))
        from rpg_vkr.domain.catalog_actions import ActorAttempt

        if isinstance(turn.catalog, ActorAttempt) and (
            turn.catalog.entity_before.state.get("hp", 0) > 0
            and turn.catalog.entity_after.state.get("hp") == 0
        ):
            key = "victory:" + turn.catalog.target_id
            result.setdefault(key, (50, "Первая победа над противником", index))
        if turn.gameplay:
            record = turn.gameplay
            for actor_id in set(record["result"]["state"]["victories"]) - victories:
                result.setdefault(
                    "victory:" + actor_id, (50, "Первая победа над противником", index)
                )
            victories.update(record["result"]["state"]["victories"])
        if turn.challenge and turn.challenge.check.succeeded:
            key = "challenge:" + turn.challenge.location + ":" + turn.challenge.kind
            result.setdefault(key, (10, "Первая успешная проверка задачи", index))
    return result


def synchronized(progress, turns):
    if progress is None:
        return None
    known = {e.event_id for e in progress.events}
    for key, (amount, reason, _) in achievements(turns).items():
        if key not in known:
            progress = progress.grant_xp(key, amount, reason)
    return progress


def validate_progress(progress, turns):
    if progress is None:
        return
    earned = achievements(turns)
    for event in progress.events:
        if event.kind == "xp" and (
            event.event_id not in earned
            or (event.amount, event.reason) != earned[event.event_id][:2]
        ):
            raise ValueError("Награда не подтверждена событием кампании.")
    if synchronized(progress, turns) != progress:
        raise ValueError("В сохранении пропущено подтверждённое развитие.")
    for index, turn in enumerate(turns, 1):
        if turn.challenge and turn.challenge.version == "challenge-homebrew-3":
            spec = turn.challenge.assessment
            prefix = D20Progress(progress.events[: spec["revision"]])
            if (
                spec["revision"] > len(progress.events)
                or prefix.rank(spec["skill"]) != spec["rank"]
            ):
                raise ValueError("Бонус навыка не совпадает с историей обучения.")
            if any(e.kind == "xp" and earned[e.event_id][2] >= index for e in prefix.events):
                raise ValueError("Проверка использует ещё не полученный опыт.")
