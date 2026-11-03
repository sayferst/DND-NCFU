"""Explainable receipt checks and an optional tiny, separately trained classifier."""

import math
import re
from collections import Counter


def inspect(receipt, narration=""):
    findings = []
    if not receipt or receipt.get("committed") is not True:
        return [{"code": "UNCONFIRMED_RESULT", "severity": "critical"}]
    attempt = receipt.get("free_attempt", {})
    if attempt.get("mode") == "ATTEMPT_WITHOUT_TARGET_SUCCESS":
        if attempt.get("dice"):
            findings.append({"code": "UNNECESSARY_ROLL", "severity": "critical"})
        if re.search(
            r"(?<!не )\b(?:монеты появились|взлетаешь|золото получено)\b", narration.casefold()
        ):
            findings.append({"code": "UNCONFIRMED_CAPABILITY", "severity": "critical"})
    if re.search(r"\b(?:ты решил|вы решили|ты согласился|вы согласились)\b", narration.casefold()):
        findings.append({"code": "PLAYER_AGENCY", "severity": "review"})
    return findings


def tokens(text):
    return re.findall(r"[a-zа-яё]{2,}", text.casefold())


def fit(rows):
    """Multinomial NB; no self-approval. No artifact if human data is absent."""
    if not rows:
        raise ValueError("BLOCKED_DATA: human-reviewed critic labels required")
    classes, counts, totals, families = Counter(), {}, Counter(), set()
    for row in rows:
        if (
            row.get("review_status") != "HUMAN_APPROVED"
            or not row.get("reviewer")
            or row.get("label") not in ("+", "-")
            or not row.get("family")
        ):
            raise ValueError("Unreviewed classifier record")
        label = row["label"]
        classes[label] += 1
        counts.setdefault(label, Counter()).update(tokens(row["action"]))
        totals[label] = sum(counts[label].values())
        families.add(row["family"])
    if set(classes) != {"+", "-"} or len(families) < 2:
        raise ValueError("BLOCKED_DATA: independent families and both classes required")
    return {
        "schema": "strategic-critic-nb-v1",
        "classes": dict(classes),
        "counts": {k: dict(v) for k, v in counts.items()},
        "totals": dict(totals),
        "families": sorted(families),
        "human_reviewed": len(rows),
        "evaluation": "REQUIRES_INDEPENDENT_FAMILY_HOLDOUT",
    }


def predict(model, text):
    vocabulary = set().union(*(set(v) for v in model["counts"].values()))
    scores = {}
    for label, count in model["classes"].items():
        scores[label] = math.log(count / sum(model["classes"].values())) + sum(
            math.log(
                (model["counts"][label].get(word, 0) + 1)
                / (model["totals"][label] + len(vocabulary))
            )
            for word in tokens(text)
        )
    return {
        "suggested_label": max(scores, key=scores.get),
        "scores": scores,
        "status": "AI_SUGGESTED",
        "human_approved": False,
    }
