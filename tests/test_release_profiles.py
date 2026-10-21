"""Public build configuration must contain an HTTPS service address and no secrets."""

import json

import pytest

from scripts.release_tools import prepare_release_profile


def test_tester_build_requires_https_and_records_only_public_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("DND_BUILD_PROFILE", "tester")
    monkeypatch.delenv("DND_GATEWAY_URL", raising=False)
    with pytest.raises(ValueError, match="HTTPS"):
        prepare_release_profile(tmp_path / "profile.json")
    monkeypatch.setenv("DND_GATEWAY_URL", "https://game.example.org:8443/api/v1")
    monkeypatch.setenv("DND_ROUTERAI_KEY", "owner-secret-never-bundled")
    monkeypatch.setenv("DND_TESTER_TOKEN", "scoped-token-never-bundled")
    output = prepare_release_profile(tmp_path / "profile.json")
    data = json.loads(output.read_text())
    assert set(data) == {"mode", "gateway", "text_model", "commit"}
    assert "secret" not in output.read_text() and "token" not in output.read_text()
    assert data["mode"] == "tester" and data["commit"]
