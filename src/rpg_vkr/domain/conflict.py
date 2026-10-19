"""Small finite-game reference solver; utilities are explicit homebrew assumptions."""

from math import isfinite


def analyse_game(payoffs):
    if not payoffs or not payoffs[0] or any(len(r) != len(payoffs[0]) for r in payoffs):
        raise ValueError("Expected a rectangular nonempty payoff matrix")
    if any(
        len(p) != 2 or any(type(v) not in (int, float) or not isfinite(v) for v in p)
        for row in payoffs
        for p in row
    ):
        raise ValueError("Invalid utility")
    rows, cols = len(payoffs), len(payoffs[0])
    pure = tuple(
        (i, j)
        for i in range(rows)
        for j in range(cols)
        if all(payoffs[i][j][0] >= payoffs[k][j][0] for k in range(rows))
        and all(payoffs[i][j][1] >= payoffs[i][k][1] for k in range(cols))
    )
    security = tuple(min(payoffs[i][j][1] for i in range(rows)) for j in range(cols))
    return {
        "pure_nash": pure,
        "npc_security": security,
        "npc_maximin": tuple(j for j, v in enumerate(security) if v == max(security)),
    }


def peaceful_contact():
    # Rows are hypothetical player choices, not predictions or forced player actions.
    payoffs = (((3, 3), (1, 2)), ((0, -1), (-1, 0)))
    return {
        "version": "contact-game-homebrew-1",
        "assumption": "Условная модель, не измеренные предпочтения и не прогноз игрока.",
        "player_options": ["cooperate", "escalate"],
        "npc_options": ["ask_reason", "keep_watch"],
        "payoffs": payoffs,
        **analyse_game(payoffs),
        "use": "Совет о реакции NPC; не выбирай за игрока и не назначай награду/бой.",
    }
