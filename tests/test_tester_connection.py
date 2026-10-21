"""A tester needs only a scoped activation token, never an owner RouterAI key."""

import base64
import json

import pytest
from test_adventure import hero, world_value
from test_gateway import running
from test_local_narrator import wait_for
from test_photo_album import png

from rpg_vkr.deployment import ReleaseProfile, gateway_url
from rpg_vkr.storage.connection import ConnectionPreferences
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.cloud_gate import cloud_ready
from rpg_vkr.ui.main_window import MainWindow


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:password@example.com",
        "https://example.com/?key=secret",
        "https://example.com/other",
    ],
)
def test_gateway_urls_reject_insecure_or_credential_bearing_configuration(url):
    with pytest.raises(ValueError):
        gateway_url(url)


def test_tester_world_and_image_use_only_gateway_after_owner_config_exists(
    qt_app, tmp_path, monkeypatch
):
    import rpg_vkr.ui.tester_connection as connection

    with running(tmp_path / "server") as (base, token, _, upstream, _):
        profile = ReleaseProfile("tester", base)
        monkeypatch.setattr(connection, "load_release_profile", lambda: profile)
        monkeypatch.setenv("DND_TESTER_TOKEN", token)
        monkeypatch.setenv("RPG_VKR_ROUTERAI_API_KEY", "owner-key-must-not-be-used")
        root = tmp_path / "client"
        root.mkdir()
        ConnectionPreferences("routerai", "deepseek/owner-flash", True, True).save(
            root / "ai-connection.json"
        )
        original = upstream.request

        def response(route, body=None):
            if route == "chat/completions":
                upstream.posts.append((route, body))
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(world_value(), ensure_ascii=False),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "model": profile.text_model,
                    "cost_rub": 0.01,
                }
            if route == "images":
                upstream.posts.append((route, body))
                return {"data": [{"b64_json": base64.b64encode(png()).decode()}], "cost_rub": 1}
            return original(route, body)

        upstream.request = response
        window = MainWindow(session=hero(), saves=SaveSlots(root / "saves"))
        window.show()
        monkeypatch.setattr(window, "_confirm", lambda _: True)
        try:
            qt_app.processEvents()
            assert cloud_ready(window) and not window.cloud_key.text()
            assert window.ollama.cloud.provider == "gateway"
            assert window.ollama.cloud.key == token and not upstream.posts
            window.show_world_creation()
            window.world_creation_screen.create_button.click()
            wait_for(qt_app, lambda: not window.ollama.busy)
            assert window._session.generated_world, (
                window.narrator_status.text(),
                window.narrator_details.toPlainText(),
                upstream.posts,
                window.world_creation_screen.detail.text(),
            )
            assert upstream.posts[0][1]["max_tokens"] == 65536
            window.visuals.ask = lambda *args: True
            window.visuals.request_scene()
            wait_for(
                qt_app, lambda: window.visuals.active is None and not window.visuals.worker.busy
            )
            assert [r for r, _ in upstream.posts] == ["chat/completions", "images"]
            assert len(window.visuals.registry.campaign_assets(window.photo_album.campaign)) == 1
            assert window.visuals.registry.totals()["actual"] == 1000000
            window.open_section("Фотоальбом")
            assert window.photo_album.list.count() == 1
            for path in root.rglob("*.json"):
                text = path.read_text()
                assert token not in text and "owner-key-must-not-be-used" not in text
        finally:
            window._dirty = False
            window.close()


def test_tester_without_server_stays_unconfigured_without_owner_fallback(
    qt_app, tmp_path, monkeypatch
):
    import rpg_vkr.ui.tester_connection as connection

    monkeypatch.setattr(connection, "load_release_profile", lambda: ReleaseProfile("tester"))
    monkeypatch.setenv("RPG_VKR_ROUTERAI_API_KEY", "owner-key")
    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    try:
        qt_app.processEvents()
        assert not cloud_ready(window)
        assert window.ollama.cloud is None and not window.cloud_key.text()
    finally:
        window.close()
