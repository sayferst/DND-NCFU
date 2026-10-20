"""Explicit offline release probe, isolated from every real campaign and provider."""

import base64
import json
import os
import platform
import sys
import tempfile
import threading
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@contextmanager
def loopback():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, body))
            value = (
                {"data": [{"b64_json": base64.b64encode(PNG).decode()}], "usage": {"cost": 0.97}}
                if self.path == "/images"
                else {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "Ветер колышет траву."},
                            "finish_reason": "stop",
                        }
                    ]
                }
            )
            raw = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def smoke_test(app):
    from rpg_vkr.application import Session
    from rpg_vkr.domain.adventure import build_world
    from rpg_vkr.domain.character import Character
    from rpg_vkr.narrative.cloud import CloudProfile, normalize_completion
    from rpg_vkr.resources import RESOURCE_ROOT
    from rpg_vkr.storage.campaigns import CampaignRepository
    from rpg_vkr.storage.connection import load_secret, save_secret, windows_credentials_available
    from rpg_vkr.storage.slots import SaveSlots
    from rpg_vkr.ui.main_window import MainWindow
    from rpg_vkr.visuals.client import ImagesTransport
    from rpg_vkr.visuals.context import reference_candidates, scene_target
    from rpg_vkr.visuals.policy import FLUX, payload, quote_model
    from rpg_vkr.visuals.registry import VisualRegistry

    with tempfile.TemporaryDirectory(prefix="DND-probe-") as temporary:
        root = Path(temporary)
        names = ("RPG_VKR_DATA_DIR", "RPG_VKR_ROUTERAI_API_KEY", "RPG_VKR_LLM_API_KEY")
        old = {name: os.environ.get(name) for name in names}
        for name in names:
            os.environ.pop(name, None)
        os.environ["RPG_VKR_DATA_DIR"] = str(root / "data")
        try:
            session = Session.create_hero(Character(name="Проверка"), "scholar", seed=137)
            seed = build_world(
                {
                    "title": "Проверка упаковки",
                    "opening": "Тихий двор.",
                    "private_plot": "Только проверка хранения, не пользовательское приключение.",
                    "hooks": ["Осмотреть двор"],
                    "start": "yard",
                    "places": [
                        {"id": "yard", "name": "Двор", "parent": "", "description": "Тихий двор."}
                    ],
                    "definitions": [
                        {
                            "id": "probe_npc_type",
                            "name": "Проверочный персонаж",
                            "kind": "actor",
                            "categories": ["npcs"],
                            "properties": {"hp_max": 10, "appearance": "Серый плащ"},
                        }
                    ],
                    "entities": [
                        {
                            "id": "probe_npc",
                            "definition_id": "probe_npc_type",
                            "parent_id": "yard",
                            "state": {"hp": 10},
                        }
                    ],
                },
                session,
                "offline-packaging-probe",
            )
            session.start_world(seed)
            slots = SaveSlots(root / "data/saves")
            slots.save(1, session)
            restored = slots.load(1)
            if (
                restored.to_dict() != session.to_dict()
                or restored.dice.roll_d20() != session.dice.roll_d20()
            ):
                raise ValueError("Save/RNG roundtrip failed")
            # Do not save the deliberately consumed probe roll.
            restored = slots.load(1)
            database = CampaignRepository(root / "data/campaigns.sqlite3")
            database.sync(restored)
            if database.load(database.identity(restored)).to_dict() != restored.to_dict():
                raise ValueError("SQLite roundtrip failed")
            registry = VisualRegistry(root / "data/visuals")
            campaign = database.identity(restored)
            request = registry.reserve(campaign, "entity:probe_npc", "offline-fixture", 1, 100)
            registry.mark_submitted(request)
            registry.complete(request, PNG, actual=0)
            registry.bind(campaign, "probe_npc", "entity:probe_npc")
            scene = scene_target(restored)
            candidates = reference_candidates(VisualRegistry(root / "data/visuals"), scene)
            if not candidates:
                raise ValueError("Persistent visual reference missing")
            with loopback() as (base, calls):
                quote = quote_model(
                    {
                        "data": [
                            {
                                "id": FLUX,
                                "pricing": {"image_output": "0.97"},
                                "pricing_units": {"image_output": "image"},
                            }
                        ]
                    },
                    FLUX,
                    "1K",
                    1,
                )
                body = payload(
                    quote,
                    "Offline packaging probe",
                    ["data:image/png;base64," + base64.b64encode(PNG).decode()],
                )
                image, cost, _ = ImagesTransport(test_base=base).generate(body, "probe-key")
                if not image.startswith(b"\x89PNG") or cost != 970000:
                    raise ValueError("Image contract failed")
                profile = CloudProfile("routerai", "deepseek/deepseek-v4-flash-latest", "probe-key")
                text_body = profile.payload(
                    {"messages": [{"role": "user", "content": "Только локальная проверка"}]}
                )
                req = urllib.request.Request(
                    base + "/chat/completions",
                    data=json.dumps(text_body).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    text = normalize_completion(json.load(response))
                if text["message"]["content"] != "Ветер колышет траву." or len(calls) != 2:
                    raise ValueError("Chat contract failed")
            credential = "unavailable-on-this-platform"
            if windows_credentials_available():
                path = root / "probe-credential.bin"
                key = "probe-not-a-real-provider-key"
                save_secret(path, key)
                if load_secret(path) != key or key.encode() in path.read_bytes():
                    raise ValueError("Native DPAPI roundtrip failed")
                credential = "native-roundtrip-passed"
            window = MainWindow(session=restored, saves=slots)
            window._confirm = lambda *_: True
            try:
                window.show()
                app.processEvents()
                sections = [window.tabs.tabText(i) for i in range(window.tabs.count())]
                for section in ("Главное меню", "Герой", "Хроники мира", "Мастер", "Художник"):
                    window.open_section(section)
                    app.processEvents()
                    if window.tabs.tabText(window.tabs.currentIndex()) != section:
                        raise ValueError("Packaged GUI section missing")
                window.chronicles_panel.open_entry("probe_npc")
                if not window.visuals.registry.latest_for(campaign, "probe_npc"):
                    raise ValueError("Packaged UI cache missing")
            finally:
                window.close()
                window.deleteLater()
                app.processEvents()
            if getattr(sys, "frozen", False):
                import _sqlite3
                import _ssl

                import PySide6

                for module in (_sqlite3, _ssl, PySide6):
                    origin = getattr(module, "__file__", None)
                    if origin is None and module.__name__ in sys.builtin_module_names:
                        # Some build interpreters embed stdlib extensions in libpython.
                        continue
                    if origin is None or not Path(origin).resolve().is_relative_to(
                        RESOURCE_ROOT.resolve()
                    ):
                        raise ValueError("Dependency loaded outside bundle")
            return {
                "mode": "smoke-test",
                "ok": True,
                "platform": platform.platform(),
                "save_json": True,
                "save_sqlite": True,
                "rng": True,
                "visual_cache": True,
                "references": True,
                "gui_sections": sections,
                "dpapi": credential,
                "loopback_posts": 2,
                "network_requests": 2,
                "external_model_requests": 0,
                "clean_windows_without_python": "requires separate manual acceptance",
            }
        finally:
            for name, value in old.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
