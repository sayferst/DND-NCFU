"""Map bounded provider error metadata to fixed reasons; never retain its original text."""

import json
import re


def classify(raw):
    """Returns two allowlisted labels, never JSON fields, messages, headers or URLs."""
    raw = raw[:8192]
    response_format = "json"
    try:
        value = json.loads(raw)
    except (ValueError, TypeError, RecursionError):
        sample = raw[:1024].lower()
        if b"<html" in sample or b"<!doctype html" in sample:
            return "unrecognized", "html"
        value = raw.decode("utf-8", errors="replace")
        response_format = "text"
    fragments = []

    def collect(node, depth=0):
        if depth > 3:
            return
        if isinstance(node, str):
            fragments.append(node[:2048])
        elif isinstance(node, dict):
            for field in ("error", "message", "detail", "code", "type"):
                if field in node:
                    collect(node[field], depth + 1)
        elif isinstance(node, list) and len(node) == 1:
            collect(node[0], depth + 1)

    collect(value)
    text = "\n".join(re.sub(r"[_\s-]+", " ", part.casefold()) for part in fragments)[:8192]
    key = bool(re.search(r"\b(?:api\s*)?key\b|\btoken\b", text))
    master = key and bool(re.search(r"\b(?:master|admin|administrative|management)\b", text))
    if master:
        if re.search(r"\b(?:requires?|required|missing)\b", text) and not re.search(
            r"\bnot\b", text
        ):
            return "master_key_required", response_format
        return "master_key_not_supported", response_format
    if "authorization" in text or "bearer" in text:
        if re.search(r"\b(?:invalid|malformed|format|expected|incorrect)\b", text):
            return "authorization_format", response_format
        if re.search(r"\b(?:missing|required|empty|absent)\b|not provided", text):
            return "authorization_missing", response_format
    if re.search(
        r"\b(?:invalid|malformed|incorrect|unknown) (?:api )?(?:key|token)\b"
        r"|\b(?:api )?(?:key|token)\b.{0,35}\b(?:invalid|malformed|incorrect|not found)\b",
        text,
    ):
        return "key_rejected", response_format
    if key and re.search(r"\b(?:disabled|revoked|expired|inactive)\b", text):
        return "key_inactive", response_format
    if key and re.search(r"\b(?:missing|required|empty|absent)\b|not provided", text):
        return "authorization_missing", response_format
    if re.search(r"\b(?:json|body)\b", text) and re.search(
        r"\b(?:invalid|empty|unexpected|parse|required|missing)\b", text
    ):
        return "body_rejected", response_format
    if re.search(r"\b(?:route|endpoint|method)\b", text) and re.search(
        r"\b(?:unsupported|unknown|invalid)\b|not found|not allowed", text
    ):
        return "operation_unavailable", response_format
    if re.search(r"insufficient (?:balance|credit|funds)|quota exceeded|limit exceeded", text):
        return "quota_rejected", response_format
    if re.search(r"\b(?:permission|forbidden)\b|access denied|not permitted", text):
        return "access_denied", response_format
    return "unrecognized", response_format
