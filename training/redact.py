"""Mark unsafe inputs for review; never silently manufacture approval or a receipt."""

from copy import deepcopy

from training.schema import validate


def redact(row):
    candidate = deepcopy(row)
    ok, reason = validate(candidate)
    if not ok:
        candidate["review_status"] = "needs_review"
    return candidate, reason
