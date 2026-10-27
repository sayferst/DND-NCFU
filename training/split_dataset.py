"""Reuse deterministic family and near-duplicate grouping; campaigns never cross splits."""

from types import SimpleNamespace

from rpg_vkr.learning.quality import grouped


def split(rows):
    ids = [r["sample_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate sample IDs")
    adapters = [
        SimpleNamespace(
            record_id=r["sample_id"],
            family_id=r["campaign_id"],
            title="",
            record_type="session",
            source_id="gm-sft-v1",
            category=r["scene_mode"],
            text="header\n" + r["player_message"] + "\n" + r["assistant_reply"],
        )
        for r in rows
    ]
    groups, parts, diagnostics = grouped(adapters)
    result = {"train": [], "val": [], "test": []}
    for row in rows:
        result["val" if parts[row["sample_id"]] == "dev" else parts[row["sample_id"]]].append(row)
    return result, diagnostics
