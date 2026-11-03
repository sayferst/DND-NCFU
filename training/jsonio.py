"""Strict JSON parsing for offline training artifacts."""

import json


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("Non-finite JSON number")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
