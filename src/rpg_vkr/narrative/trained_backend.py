"""Owner-controlled, evaluated narrator only. No weights or training in the client."""

import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from rpg_vkr.resources import data_directory


def approved(path=None):
    path = Path(path) if path else data_directory() / "trained-narrator.json"
    try:
        if path.stat().st_size > 12000:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if (
            value["approved_for_runtime"] is not True
            or value["evaluation"]["critical_regression"] is not False
            or value["evaluation"]["holdout_campaigns"] < 1
        ):
            return None
        url = urlsplit(value["endpoint"])
        if (
            url.scheme != "http"
            or url.hostname not in ("127.0.0.1", "localhost")
            or url.username
            or url.password
            or url.path not in ("", "/")
        ):
            return None
        adapter = Path(value["adapter_path"])
        if (
            adapter.name != "adapter_model.safetensors"
            or adapter.is_symlink()
            or not 0 < adapter.stat().st_size <= 512 * 1024 * 1024
        ):
            return None
        digest = hashlib.sha256()
        with adapter.open("rb") as f:
            while block := f.read(1024 * 1024):
                digest.update(block)
        if digest.hexdigest() != value["adapter_sha256"]:
            return None
        if not isinstance(value["model"], str) or not 1 <= len(value["model"]) <= 120:
            return None
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return None


def dispatch(client, frame, model, text, kwargs):
    if getattr(client, "_trained_bypass", False):
        return False
    spec = approved()
    if not spec:
        return False
    from rpg_vkr.narrative.ollama import OllamaClient

    child = OllamaClient(client)
    client._trained_child = child
    child._trained_bypass = True
    child.base_url = spec["endpoint"].rstrip("/")
    child.models = [spec["model"]]
    child.proposal_ready.connect(client.proposal_ready.emit)
    child.narration_ready.connect(client.narration_ready.emit)
    child.progress.connect(client.progress.emit)
    child.busy_changed.connect(client.busy_changed.emit)
    child.event_ready.connect(client.event_ready.emit)

    def fallback(reason):
        client._trained_child = None
        client._trained_bypass = True
        try:
            client._start_story(frame, model, text, **kwargs)
        finally:
            client._trained_bypass = False

    child.failed.connect(fallback)
    child._start_story(frame, spec["model"], text, **kwargs)
    return True
