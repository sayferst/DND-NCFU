"""Private owner bootstrap with simulated DPAPI; never access real credentials or network."""

import base64
import json

import pytest

from rpg_vkr import owner_local as owner
from rpg_vkr.deployment import ReleaseProfile


def test_binding_checks_windows_user_and_machine(monkeypatch):
    payloads = {}

    def protect(value, *, decrypt=False):
        if decrypt:
            return payloads[value]
        payloads[b"fake-user-cipher"] = value
        return b"fake-user-cipher"

    monkeypatch.setattr(owner, "_dpapi", protect)
    monkeypatch.setattr(owner, "machine_id", lambda: "machine-one")
    binding = owner.create_binding()
    owner.verify_binding(binding)
    monkeypatch.setattr(owner, "machine_id", lambda: "machine-two")
    with pytest.raises(ValueError, match="другому ПК"):
        owner.verify_binding(binding)

    def unavailable(*args, **kwargs):
        raise OSError("different user")

    monkeypatch.setattr(owner, "_dpapi", unavailable)
    with pytest.raises(ValueError, match="другому ПК"):
        owner.verify_binding(binding)


def test_owner_profile_does_not_bundle_api_key(tmp_path, monkeypatch):
    from scripts.release_tools import prepare_release_profile

    proof = base64.b64encode(b"fake-dpapi-binding").decode()
    monkeypatch.setenv("DND_BUILD_PROFILE", "owner")
    monkeypatch.setenv("DND_ACCOUNT_LOGIN", "")
    monkeypatch.setattr(owner, "create_binding", lambda: proof)
    monkeypatch.setattr(owner, "admin_key", lambda: pytest.fail("key must not be bundled"))
    path = prepare_release_profile(tmp_path / "profile.json")
    value = json.loads(path.read_text())
    assert value["mode"] == "owner" and value["owner_binding"] == proof
    assert "account_login" not in value and "api_key" not in value
    with pytest.raises(ValueError):
        ReleaseProfile(mode="owner")
    with pytest.raises(ValueError):
        ReleaseProfile(owner_binding=proof)


def test_admin_key_is_loaded_again_after_change(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    saved = ["synthetic-first"]
    paths = []
    monkeypatch.setattr(owner, "load_secret", lambda path: paths.append(path) or saved[0])
    assert owner.admin_key() == "synthetic-first"
    saved[0] = "synthetic-second"
    assert owner.admin_key() == "synthetic-second"
    assert paths == [tmp_path / "DND-NCFU-Host" / "account-admin-key.bin"] * 2
    saved[0] = ""
    with pytest.raises(ValueError, match="CHANGE_ADMIN_API"):
        owner.admin_key()


def test_owner_builder_needs_neither_host_nor_installer(tmp_path, monkeypatch):
    from scripts import tester_host

    monkeypatch.setattr(tester_host, "ROOT", tmp_path)
    monkeypatch.setattr(owner, "admin_key", lambda: "sk-fixture-only-key")
    monkeypatch.setattr(tester_host, "build_preflight", lambda root: pytest.fail("no host check"))
    monkeypatch.setattr(tester_host, "inno_compiler", lambda: pytest.fail("no Inno required"))

    def build(command, **kwargs):
        assert command[-2:] == ["-Profile", "owner"] and "-Installer" not in command
        bundle = tmp_path / "dist" / "DND-NCFU"
        bundle.mkdir(parents=True)
        (bundle / "DND-NCFU.exe").write_bytes(b"synthetic-exe")

    monkeypatch.setattr(tester_host.subprocess, "run", build)
    tester_host.build_owner()
    assert len(list((tmp_path / "dist").glob("Owner-*/DND-NCFU.exe"))) == 1
    assert not (tmp_path / "dist" / "DND-NCFU").exists()


def test_owner_starts_as_admin_without_login_or_gateway(qt_app, tmp_path, monkeypatch):
    from rpg_vkr.storage.slots import SaveSlots
    from rpg_vkr.ui import tester_connection
    from rpg_vkr.ui.main_window import MainWindow

    proof = base64.b64encode(b"fake-proof").decode()
    monkeypatch.setattr(owner, "verify_binding", lambda binding: None)
    monkeypatch.setattr(owner, "admin_key", lambda: "sk-fixture-only-key")
    monkeypatch.setattr(
        tester_connection,
        "load_release_profile",
        lambda: ReleaseProfile(mode="owner", owner_binding=proof),
    )
    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    try:
        qt_app.processEvents()
        assert window._account_name == "admin"
        assert window.developer_console.access.authorized
        assert window.ollama.cloud and window.local_model.currentText()
        assert window.cloud_key.text() == "sk-fixture-only-key"
        assert window.artist_panel.effective_key() == "sk-fixture-only-key"
        assert not window.visuals.worker.transport.gateway
        assert not hasattr(window, "tester_connection_worker")
        assert window.developer_console.enter() is True
    finally:
        window.close()
