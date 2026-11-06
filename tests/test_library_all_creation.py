"""Every spawnable record must build a valid proposal without touching a world."""

from collections import Counter

from test_owner_rules_runtime import campaign

from rpg_vkr.world_library.bridge import is_descriptive, preview
from rpg_vkr.world_library.model import all_records
from rpg_vkr.world_library.store import Library


def test_all_spawnable_templates_build_valid_inert_creation_proposals(tmp_path):
    library = Library.sqlite(tmp_path / "new-global-library.sqlite3")
    try:
        library.migrate()
        records = all_records()
        library.import_records(records)
        session = campaign(hp=12)
        before, rng = session.to_dict(), session.dice.checkpoint()
        checked = Counter()
        for row in records:
            if is_descriptive(row):
                continue
            proposal = preview(
                library,
                session,
                row["id"],
                "preview_entity",
                with_inventory=row["profile"] == "npc",
            )
            assert proposal.entities[0].id == "preview_entity", row["id"]
            checked[row["profile"]] += 1
        assert sum(checked.values()) == 7087 + sum(
            bool(r["attributes"].get("source_spell_v1")) for r in records
        )
        assert checked["source_creature"] == 3920 and checked["npc"] == 400
        assert session.to_dict() == before and session.dice.checkpoint() == rng
        assert library.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not library.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        library.close()
