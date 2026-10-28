"""Offline release checks. No user campaigns, credentials or model calls are opened."""

import json
import platform
import ssl
import sys
from pathlib import Path

from rpg_vkr.build_info import VERSION
from rpg_vkr.resources import REQUIRED_RESOURCES, RESOURCE_ROOT, data_directory, resource_path


def check_resources(progress=lambda value, label: None):
    from dataclasses import asdict

    from PySide6.QtGui import QImage

    from rpg_vkr.deployment import load_release_profile

    checks = []
    for i, relative in enumerate(REQUIRED_RESOURCES):
        path = resource_path(relative)
        if not path.is_file() or not path.stat().st_size:
            raise FileNotFoundError("Missing required resource: " + relative)
        if path.suffix.lower() in {".png", ".ico"} and QImage(str(path)).isNull():
            raise ValueError("Invalid image resource: " + relative)
        checks.append(relative)
        progress(10 + i * 5, "Ресурсы мира")
    from rpg_vkr.domain.catalog import seed_catalog
    from rpg_vkr.domain.object_descriptions import default_profiles
    from rpg_vkr.narrative.genres import cards
    from rpg_vkr.narrative.instructions import load_instructions

    if not seed_catalog().definitions or not cards() or not default_profiles():
        raise ValueError("Static game data is empty.")
    load_instructions(
        default_path=resource_path("prompts/master_system_prompt.txt"),
        local_path=RESOURCE_ROOT / ".no-personal-prompt-self-check",
    )
    progress(60, "Каталоги и инструкции")
    import sqlite3

    from PySide6.QtNetwork import QSslSocket

    with sqlite3.connect(":memory:") as db:
        if db.execute("SELECT 1").fetchone() != (1,):
            raise ValueError("SQLite unavailable")
    ssl.create_default_context()
    if not QSslSocket.supportsSsl():
        raise RuntimeError("Qt TLS backend unavailable")
    import base64
    import time

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from rpg_vkr.discovery import canonical, verify

    # Verifies native crypto imports in the actual frozen binary, without network or owner keys.
    key = Ed25519PrivateKey.generate()
    now = int(time.time())
    value = {
        "version": 1,
        "sequence": 1,
        "issued": now,
        "expires": now + 60,
        "endpoint": "https://offline.example.org/api/v1",
    }
    signature = base64.b64encode(key.sign(canonical(value))).decode()
    public = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    verify(json.dumps(value | {"signature": signature}).encode(), public)
    progress(75, "Хранилище и защищённое соединение")
    from rpg_vkr.domain.game_catalog import digest, load, using
    from rpg_vkr.learning.corpus import diagnostics

    with using(3):
        catalog_report = {"count": len(load()), "sha256": digest(), "revision": 3}

    return {
        "ok": True,
        "mode": "self-check",
        "version": VERSION,
        "release_profile": asdict(load_release_profile()),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "resources": checks,
        "qt_tls": True,
        "discovery_signature": "native-roundtrip-passed",
        "python_tls": ssl.OPENSSL_VERSION,
        "sqlite": sqlite3.sqlite_version,
        "data_outside_application": str(data_directory()),
        "network_requests": 0,
        "automatic_corpus": diagnostics(),
        "game_catalog": catalog_report,
    }


def write_report(path, report):
    if path:
        target = Path(path).resolve()
        if getattr(sys, "frozen", False) and target.is_relative_to(
            Path(sys.executable).resolve().parent
        ):
            raise ValueError("Diagnostic report must be outside the application directory.")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
    if sys.stdout:
        # Windows redirected consoles can use CP1252 even for a Russian game.
        # Keep the file UTF-8; machine-readable stdout must fit every code page.
        print(json.dumps(report, ensure_ascii=True), flush=True)
