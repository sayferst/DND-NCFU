"""Public release assets cannot embed the owner's gateway or activation."""

import json

import pytest

from scripts.release_tools import prepare_bootstrap, prepare_release_profile


def test_public_profile_contains_no_keys_or_gateway(tmp_path, monkeypatch):
    for name in ("DND_BUILD_PROFILE", "DND_GATEWAY_URL", "DND_DISCOVERY_URL", "DND_DISCOVERY_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DND_ROUTERAI_KEY", "synthetic-owner-key")
    monkeypatch.setenv("DND_TESTER_TOKEN", "synthetic-player-token")
    output = prepare_release_profile(tmp_path / "profile.json")
    value = json.loads(output.read_text())
    assert value["mode"] == "developer" and value["gateway"] == ""
    assert "synthetic" not in output.read_text()


@pytest.mark.parametrize(
    "name,value",
    [
        ("DND_BUILD_PROFILE", "tester"),
        ("DND_GATEWAY_URL", "https://example.org/api/v1"),
        ("DND_DISCOVERY_URL", "https://example.org/endpoint.json"),
    ],
)
def test_public_profile_rejects_private_deployment(tmp_path, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="Public builds"):
        prepare_release_profile(tmp_path / "profile.json")


def test_personal_activation_is_rejected_before_reading_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DND_BOOTSTRAP_FILE", str(tmp_path / "must-not-open.json"))
    with pytest.raises(ValueError, match="personal activation"):
        prepare_bootstrap(tmp_path / "bootstrap.json")


def test_shared_installer_contains_only_public_signature_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DND_BUILD_PROFILE", "tester")
    monkeypatch.setenv(
        "DND_DISCOVERY_URL",
        "https://raw.githubusercontent.com/sayferst/DND-NCFU/tester-host-address/endpoint.json",
    )
    monkeypatch.setenv("DND_DISCOVERY_KEY", "5lGcAqnkdVgVF2TlrY7TRuZyRgvdIQZZ733zsORo6eo=")
    monkeypatch.delenv("DND_GATEWAY_URL", raising=False)
    output = prepare_release_profile(tmp_path / "profile.json")
    value = json.loads(output.read_text())
    assert value["mode"] == "tester" and value["gateway"] == ""
    assert set(value) == {
        "mode",
        "gateway",
        "text_model",
        "commit",
        "discovery",
        "verification_key",
    }
