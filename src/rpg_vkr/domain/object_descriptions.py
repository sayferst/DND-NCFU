"""Public object identity, independent of mechanics, private properties and image models."""

import json
from functools import lru_cache

from rpg_vkr.resources import RESOURCE_ROOT

PROFILE_FIELDS = ("object_type", "appearance", "purpose", "material", "description")


@lru_cache(maxsize=1)
def default_profiles():
    path = RESOURCE_ROOT / "data/catalog/public-descriptions-v1.json"
    return json.loads(path.read_text(encoding="utf-8"))["profiles"]


def profile_note(note):
    """An optional compact profile fits one existing knowledge note, not a new save schema."""
    if note.private or note.kind != "knowledge":
        return {}
    try:
        value = json.loads(note.text)
    except (ValueError, TypeError):
        return {}
    if not isinstance(value, dict) or set(value) != {"field", "value"}:
        return {}
    fields = value.get("value")
    if value.get("field") != "object_profile" or not isinstance(fields, dict):
        return {}
    if not fields or not fields.keys() <= set(PROFILE_FIELDS):
        return {}
    if any(not isinstance(v, str) or not v.strip() or len(v) > 600 for v in fields.values()):
        return {}
    return fields


def object_profile(definition, state, revealed, *, observed):
    result = {}
    properties = definition["properties"]
    unidentified = properties.get("unidentified", False)
    if observed:
        if not unidentified:
            if definition.get("origin") in {"project-homebrew", "legacy-adapter"}:
                result.update(default_profiles().get(definition["id"], {}))
            from rpg_vkr.domain.catalog import CATEGORIES

            result.setdefault(
                "object_type",
                " / ".join(CATEGORIES[c].split(". ", 1)[-1] for c in definition["categories"]),
            )
        else:
            result["object_type"] = "Неопознанный предмет"
    for field in PROFILE_FIELDS:
        if field in revealed:
            result[field] = revealed[field]
    if observed:
        # Canonical public fields take precedence over a contradictory retelling.
        if not unidentified and isinstance(properties.get("appearance"), str):
            result["appearance"] = properties["appearance"]
        # Only fields explicitly marked public, plus the established visible appearance.
        for source in (properties, state):
            for field in PROFILE_FIELDS:
                value = source.get("public_" + field)
                if isinstance(value, str) and value.strip():
                    result[field] = value
    return result
