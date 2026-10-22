from dataclasses import replace

from response_cases import new_session
from test_chronicles import learn
from test_images_client import PNG

from rpg_vkr.ui.knowledge import knowledge_entries
from rpg_vkr.visuals.context import (
    STYLE,
    entity_target,
    make_prompt,
    reference_candidates,
    scene_target,
)
from rpg_vkr.visuals.registry import VisualRegistry


def test_visual_brief_never_exports_secret_name_wallet_private_notes_or_stats():
    session = new_session()
    learn(session, "public_name", "Веста")
    learn(session, "background", "SECRET-SPY", private=True)
    npc = next(e for e in knowledge_entries(session) if e.key == "vesta")
    target = entity_target(session, npc)
    assert "Веста" in target.brief
    assert (
        "SECRET-SPY" not in target.brief
        and "gold_cp" not in target.brief
        and "hp_max" not in target.brief
    )
    assert "No text" in make_prompt(target, []) and "pixel art" in STYLE
    assert session.to_dict() == session.to_dict()


def test_reference_identity_survives_100_other_images_and_restart(tmp_path):
    session = new_session()
    learn(session, "public_name", "Веста")
    npc = next(e for e in knowledge_entries(session) if e.key == "vesta")
    target = entity_target(session, npc)
    registry = VisualRegistry(tmp_path)
    request = registry.reserve(target.campaign, target.subject, "flux", 100, 100000)
    registry.mark_submitted(request)
    original = registry.complete(request, PNG)
    registry.bind(target.campaign, target.entity, target.subject)
    for i in range(100):
        request = registry.reserve(target.campaign, "other:" + str(i), "flux", 1, 100000)
        registry.mark_submitted(request)
        registry.complete(request, PNG)
    registry = VisualRegistry(tmp_path)
    scene = scene_target(session)
    assert reference_candidates(registry, scene)[0]["id"] == original["id"]
    assert not reference_candidates(registry, replace(scene, campaign="different-world"))


def test_type_images_are_shared_by_explicit_stable_type_not_name(tmp_path):
    session = new_session()
    item = next(e for e in knowledge_entries(session) if e.category == "items")
    target = entity_target(session, item, shared=True)
    assert target.subject.startswith("type:")
    assert entity_target(session, item, shared=False).subject == "entity:" + item.key


def test_hidden_identifiers_are_not_embedded_in_reference_prompt():
    session = new_session()
    scene = scene_target(session)
    prompt = make_prompt(scene, [{"subject": "entity:SECRET-SPY-ID", "caption": "Незнакомка"}])
    assert "SECRET-SPY-ID" not in prompt and "Незнакомка" in prompt


def test_note_identity_does_not_depend_on_other_memory_positions():
    from rpg_vkr.domain.adventure import MemoryNote

    session = new_session()
    note = MemoryNote("world", "event", "На мосту прозвучал колокол.", 2, False, 0, "test:event")
    session.chronicle = session.chronicle.remember((note,))
    entry = next(e for e in knowledge_entries(session) if e.description == note.text)
    first = entry.key
    other = MemoryNote("world", "knowledge", "Известна дорога к реке.", 2, False, 0, "test:extra")
    session.chronicle = replace(session.chronicle, memories=(other,) + session.chronicle.memories)
    assert next(e for e in knowledge_entries(session) if e.description == note.text).key == first
