"""gm-sft-v1 admission. No inferred engine receipts and no implicit rights grants."""

import hashlib
import json

from rpg_vkr.learning.quality import safe_excerpt

SCHEMA = "gm-sft-v1"


def validate(row):
    required = {
        "schema_version",
        "sample_id",
        "campaign_id",
        "scene_mode",
        "public_context",
        "player_message",
        "engine_receipt",
        "assistant_reply",
        "review_status",
        "rights_status",
    }
    if not isinstance(row, dict) or not required <= row.keys():
        return False, "missing_fields"
    if set(row) - required - {"synthetic", "knowledge_type", "approved_for_public_knowledge"}:
        return False, "unknown_private_fields"
    if row["schema_version"] != SCHEMA:
        return False, "schema"
    if row["review_status"] != "approved" or row["rights_status"] != "permitted":
        return False, "rights_or_review"
    if not isinstance(row["public_context"], dict) or not isinstance(row["engine_receipt"], dict):
        return False, "missing_real_receipt"
    if row.get("synthetic") is True:
        return False, "fixture_not_training_data"
    if str(row["engine_receipt"].get("provenance", "")).upper().startswith("SYNTHETIC"):
        return False, "fixture_not_training_data"
    if any(
        k in json.dumps(row["public_context"]).casefold()
        for k in (
            "private_plot",
            "secret_gm",
            "campaign_private",
            "api_key",
            "password",
            "authorization",
            "api_token",
        )
    ):
        return False, "private_context"
    for key in ("sample_id", "campaign_id", "scene_mode", "player_message", "assistant_reply"):
        if not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > 12000:
            return False, "text_bounds"
    text = json.dumps(row, ensure_ascii=False)
    if not safe_excerpt(text):
        return False, "unsafe_or_personal"
    if any(
        k in row["assistant_reply"].casefold()
        for k in ("вы решили", "вы согласились", "вы получили")
    ):
        return False, "requires_semantic_review"
    return True, "approved"


def digest(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
