"""Integer-foot positions and continuous three-dimensional source areas."""

from math import isqrt


def valid(point):
    if not isinstance(point, list) or len(point) != 3:
        raise ValueError("Position requires three integer-foot coordinates")
    if any(type(v) is not int or not -10000 <= v <= 10000 for v in point):
        raise ValueError("Invalid position coordinate")
    return point


def square(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True))


def contains(shape, origin, aim, point, length, width=5):
    for p in (origin, aim, point):
        valid(p)
    if shape == "sphere":
        return square(aim, point) <= length * length
    if shape == "self":
        return square(origin, point) <= length * length
    v = [b - a for a, b in zip(origin, aim, strict=True)]
    w = [b - a for a, b in zip(origin, point, strict=True)]
    n = sum(x * x for x in v)
    d = sum(x * y for x, y in zip(v, w, strict=True))
    m = sum(x * x for x in w)
    if not n or not m or d <= 0:
        return False
    if shape == "cone":
        # Cone diameter at distance d is d; squared tests avoid floating-point drift.
        return d * d <= length * length * n and 5 * d * d >= 4 * n * m
    if shape == "line":
        return d * d <= length * length * n and 4 * (n * m - d * d) <= width * width * n
    raise ValueError("Unknown area shape")


def positions(engine):
    state = engine.state["source_rules_v3"]
    result = state.setdefault("positions", {})
    places = {"hero": engine.scene.current} | {id: ref.place for id, ref in engine.refs.items()}
    for index, (id, place) in enumerate(sorted(places.items())):
        if id not in result or result[id]["place"] != place:
            # Explicit, saved homebrew placement when the old scene has no coordinates.
            point = [0, 0, 0] if id == "hero" else [5 * (1 + index % 8), 5 * (index // 8), 0]
            result[id] = {"point": point, "place": place, "origin": "scene-default/homebrew"}
    return result


def distance(engine, first, second):
    points = positions(engine)
    if points[first]["place"] != points[second]["place"]:
        return 1000000
    squared = square(points[first]["point"], points[second]["point"])
    root = isqrt(squared)
    return root if root * root == squared else root + 1


def move(engine, actor, destination, speed):
    valid(destination)
    if type(speed) is not int or not 0 <= speed <= 1000:
        raise ValueError("Invalid movement budget")
    source = positions(engine)[actor]
    if destination[2] != source["point"][2]:
        from rpg_vkr.world_library.source_runtime import rules

        flying = rules(engine, actor).get("fly_speed", 0)
        if engine.status_power(actor, "flight"):
            flying = max(flying, 30)
        if not flying or square(source["point"], destination) > flying * flying:
            raise ValueError("Vertical movement requires an active flight capability")
    if square(source["point"], destination) > speed * speed:
        raise ValueError("Movement exceeds the available speed")
    source["point"] = list(destination)
    source["origin"] = "engine-movement"
    engine.events.append({"kind": "source_move", "actor": actor, "to": destination, "speed": speed})


def approach(engine, actor, target, reach, speed):
    source, goal = positions(engine)[actor]["point"], positions(engine)[target]["point"]
    from rpg_vkr.world_library.source_runtime import rules

    can_fly = rules(engine, actor).get("fly_speed", 0) or engine.status_power(actor, "flight")
    axes = range(3) if can_fly else range(2)
    dest = list(source)
    for _ in range(speed):
        if square(dest, goal) <= reach * reach:
            break
        axis = max(axes, key=lambda i: abs(goal[i] - dest[i]))
        if goal[axis] == dest[axis]:
            break
        dest[axis] += 1 if goal[axis] > dest[axis] else -1
    if dest != source:
        move(engine, actor, dest, speed)
    return sum(abs(a - b) for a, b in zip(dest, source, strict=True))
