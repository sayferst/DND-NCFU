"""Explicit generation failures; literary warnings never enter this error path."""

import json


class NarrativeConflict(ValueError):
    pass


class ResponseFormatError(ValueError):
    pass


def classify(error, *, stage="", data=None, status=None):
    if status is not None:
        code = "access_or_budget" if status in {401, 402, 403, 429} else "network"
    elif isinstance(data, dict) and (
        data.get("done_reason") == "length" or data.get("done") is False
    ):
        code = "token_limit"
    elif isinstance(error, NarrativeConflict):
        code = "canon_conflict"
    elif isinstance(error, (json.JSONDecodeError, ResponseFormatError, KeyError, TypeError)):
        code = "invalid_format"
    elif stage == "world_plan":
        code = "unsupported_or_invalid_plan"
    else:
        code = "invalid_format"
    return {"code": code, "stage": stage, "reason": str(error)[:1200], "status": status}
