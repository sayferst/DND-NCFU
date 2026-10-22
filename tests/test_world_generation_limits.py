"""World output limits must reach the actual API, including a restored cold profile."""

from copy import deepcopy

import pytest
from test_adventure import hero, world_value
from test_local_narrator import wait_for
from test_routerai import MODEL, configure, router_server

from rpg_vkr.narrative.routerai import ModelQuote
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.adventure_panel import begin_world
from rpg_vkr.ui.main_window import MainWindow


@pytest.fixture
def creator(qt_app, tmp_path):
    window = MainWindow(session=hero(), saves=SaveSlots(tmp_path / "saves"))
    yield window
    window.ollama.cancel()
    window._dirty = False
    window.action_input.clear()
    window.close()
    window.deleteLater()
    qt_app.processEvents()


@pytest.mark.parametrize(
    "parameters,expected",
    [
        ((), "max_tokens"),
        (("max_tokens",), "max_tokens"),
        (("max_completion_tokens",), "max_completion_tokens"),
        (("max_tokens", "max_completion_tokens"), "max_tokens"),
    ],
)
def test_large_world_limit_reaches_api_without_extra_requests(
    creator, qt_app, monkeypatch, parameters, expected
):
    with router_server(world_seed=world_value()) as (url, records):
        configure(creator, monkeypatch, url)
        if parameters:
            creator._routerai_quotes[MODEL] = ModelQuote(MODEL, None, None, parameters)
        begin_world(creator)
        wait_for(qt_app, lambda: not creator.ollama.busy)
        assert creator._session.generated_world
        posts = [r for r in records if r["method"] == "POST"]
        assert len(posts) == 1
        assert posts[0]["body"][expected] == 65536
        assert ({"max_tokens", "max_completion_tokens"} - {expected}).isdisjoint(posts[0]["body"])
        assert creator.ollama.timer.interval() == 900000


def large_world():
    value = world_value()
    value["entities"].extend(
        {
            "id": f"rope_extra_{index}",
            "definition_id": "rope_type",
            "parent_id": "pier",
            "state": {"public_notes": "Описание верёвки. " * 180},
        }
        for index in range(18)
    )
    return value


def test_complete_world_response_over_previous_256kb_limit_is_accepted(
    creator, qt_app, monkeypatch
):
    with router_server(world_seed=large_world()) as (url, records):
        configure(creator, monkeypatch, url)
        begin_world(creator)
        wait_for(qt_app, lambda: not creator.ollama.busy)
        assert creator._session.generated_world
        assert len(creator._session.chronicle.seed.catalog.entities) == len(
            large_world()["entities"]
        )
        assert len([r for r in records if r["method"] == "POST"]) == 1


def test_provider_length_finish_still_preserves_hero_and_does_not_retry(
    creator, qt_app, monkeypatch
):
    with router_server(world_seed=world_value(), world_finish_reason="length") as (url, records):
        configure(creator, monkeypatch, url)
        before = deepcopy(creator._session.to_dict()), creator._session.dice.checkpoint()
        begin_world(creator)
        wait_for(qt_app, lambda: not creator.ollama.busy)
        assert not creator._session.generated_world and creator._generating_session is None
        assert (creator._session.to_dict(), creator._session.dice.checkpoint()) == before
        assert "ответ обрезан" in creator.world_start_status.text()
        assert len([r for r in records if r["method"] == "POST"]) == 1


def test_world_transport_still_enforces_a_bounded_response(creator, qt_app, monkeypatch):
    import rpg_vkr.narrative.ollama as transport

    monkeypatch.setattr(transport, "MAX_WORLD_RESPONSE_BYTES", 64 * 1024)
    with router_server(world_seed=large_world()) as (url, records):
        configure(creator, monkeypatch, url)
        before = deepcopy(creator._session.to_dict()), creator._session.dice.checkpoint()
        begin_world(creator)
        wait_for(qt_app, lambda: not creator.ollama.busy)
        assert not creator._session.generated_world and creator._generating_session is None
        assert (creator._session.to_dict(), creator._session.dice.checkpoint()) == before
        assert "слишком большой" in creator.world_start_status.text()
        assert len([r for r in records if r["method"] == "POST"]) == 1
