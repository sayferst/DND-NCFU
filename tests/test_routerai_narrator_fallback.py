from test_local_narrator import local_server, wait_for

from rpg_vkr.application import Session
from rpg_vkr.narrative import trained_backend
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.ollama import OllamaClient


def test_absent_adapter_never_changes_routerai_selection(tmp_path):
    assert trained_backend.approved(tmp_path / "missing") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert trained_backend.approved(bad) is None


def test_local_narrator_failure_falls_back_without_reapplying_state(qt_app, monkeypatch):
    # Synthetic transport fixture, not a claim of real trained weights.
    s = Session(seed=37)
    before = s.to_dict(), s.dice.checkpoint()
    with local_server(mode="plain_semantic_bad") as (url, requests):
        monkeypatch.setattr(
            trained_backend, "approved", lambda: {"endpoint": url, "model": "qwen3:1.7b"}
        )
        client = OllamaClient()
        client.models = ["remote-model"]
        failures = []

        def remote(path, kind, payload=None):
            failures.append((path, kind, payload))

        monkeypatch.setattr(client, "_start", remote)
        client._start_story(build_frame(s), "remote-model", "Осматриваюсь")
        wait_for(qt_app, lambda: bool(failures))
        assert len(failures) == 1 and failures[0][2]["model"] == "remote-model"
        assert len(requests) <= 2
        assert (s.to_dict(), s.dice.checkpoint()) == before
        client.cancel()
