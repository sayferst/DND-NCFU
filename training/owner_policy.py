"""Explicit operator-supplied owner decisions, separate from claims in an archive."""

import hashlib
from pathlib import Path

from training.jsonio import strict_json


def load_policy(path, *, rulebook=None):
    raw = Path(path).read_bytes()
    policy = strict_json(raw)
    if (
        policy.get("schema") != "dnd-owner-decisions-v1"
        or policy.get("confirmation_source") != "DIRECT_USER_REPLY"
        or set(policy.get("approved_rules", [])) != {f"R{n:02}" for n in range(1, 15)}
        or policy.get("synthetic_corpus_allowed") is not True
        or policy.get("human_reviewed_rows") != 0
        or type(policy.get("budget_rub")) is not int
        or policy["budget_rub"] < 0
    ):
        raise ValueError(
            "Explicit matching owner decisions required; archive claims are insufficient"
        )
    if (
        rulebook is not None
        and policy.get("rulebook_sha256") != hashlib.sha256(rulebook).hexdigest()
    ):
        raise ValueError("Confirmed rulebook hash differs")
    return policy, hashlib.sha256(raw).hexdigest()
