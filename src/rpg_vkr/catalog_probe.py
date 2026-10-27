"""Small installed-game probe using public Session actions and isolated persistence."""

from pathlib import Path

from rpg_vkr.domain.adventure import build_world
from rpg_vkr.domain.character import ABILITY_NAMES, Character
from rpg_vkr.domain.unified import CLASSES
from rpg_vkr.storage.campaigns import CampaignRepository
from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.unified_session import UnifiedSession


def probe(root):
    results = {}
    for class_id in ("mage", "artisan"):
        s = UnifiedSession.create(
            Character(**dict(zip(ABILITY_NAMES, CLASSES[class_id][3], strict=True))),
            class_id,
            CLASSES[class_id][4],
            seed=0,
            content_revision=2,
        )
        value = {
            "title": "Проверка мастерской",
            "opening": "Открытая мастерская.",
            "private_plot": "Изолированная проверка упаковки.",
            "hooks": ["Осмотреть мастерскую"],
            "start": "yard",
            "places": [
                {
                    "id": "yard",
                    "name": "Мастерская",
                    "parent": "",
                    "description": "Рабочий верстак.",
                }
            ],
            "definitions": [
                {
                    "id": "bench",
                    "name": "Верстак",
                    "kind": "item",
                    "categories": ["miscellaneous"],
                    "properties": {"station": "workbench", "public": True},
                }
            ],
            "entities": [{"id": "bench_one", "definition_id": "bench", "parent_id": "yard"}],
        }
        s.start_world(build_world(value, s, "packaged-domain-probe"))
        if class_id == "mage":
            s.perform_gameplay("cast", {"spell": "light", "target": "hero"}, "probe-cast")
        else:
            s.perform_gameplay(
                "manufacture",
                {"recipe": "recipe_production_0_0", "result": "house_0_0"},
                "probe-craft",
            )
            if not any(i.get("made_by") == "hero" for i in s.gameplay["items"]):
                raise ValueError("Packaged crafting did not produce an item")
        slots = SaveSlots(Path(root) / class_id / "saves")
        slots.save(1, s)
        restored = slots.load(1)
        if restored.to_dict() != s.to_dict():
            raise ValueError("Packaged schema31 JSON replay differs")
        repo = CampaignRepository(Path(root) / class_id / "campaigns.sqlite3")
        repo.sync(s)
        if repo.load(repo.identity(s)).to_dict() != s.to_dict():
            raise ValueError("Packaged SQLite replay differs")
        results[class_id] = {
            "schema": 31,
            "json": True,
            "sqlite": True,
            "rng": restored.dice.checkpoint() == s.dice.checkpoint(),
        }
    return results
