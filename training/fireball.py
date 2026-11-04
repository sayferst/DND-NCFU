"""FIREBALL observed HP transitions, with authored Russian narration and no Avrae rule import."""

import hashlib
import json
import re
import shutil
from collections import Counter
from pathlib import Path

from training.schema import digest

POLICY = "fireball-augmented-v1"
SCHEMA = "fireball-observed-hp-v1"
SPLITS = ("train", "val", "test")


def hp(value):
    match = re.fullmatch(r"<(\d+)/(\d+) HP; [^<>]*>", value or "")
    if not match:
        raise ValueError("UNKNOWN_OR_TEMPORARY_HP")
    current, maximum = map(int, match.groups())
    if not 0 <= current <= maximum or maximum < 1:
        raise ValueError("INVALID_HP_BOUNDS")
    return {"hp": current, "maximum": maximum}


def extract(source):
    source = Path(source)
    manifest = json.loads((source / "source-manifest.json").read_text())
    groups, rejected, seen = [], Counter(), set()
    for entry in manifest["files"]:
        raw = (source / Path(entry["path"]).name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("FIREBALL source changed")
        group = {"id": entry["path"], "controllers": set(), "rows": []}
        for index, line in enumerate(raw.splitlines()):
            record = json.loads(line)
            for actor in record.get("combat_state_before", []):
                if actor.get("controller_id"):
                    group["controllers"].add(actor["controller_id"])
            try:
                a, b = record["combat_state_before"], record["combat_state_after"]
                old = {actor["name"]: hp(actor["hp"]) for actor in a}
                new = {actor["name"]: hp(actor["hp"]) for actor in b}
                if len(old) != len(a) or len(new) != len(b) or old.keys() != new.keys():
                    raise ValueError("AMBIGUOUS_OR_CHANGED_ROSTER")
                changes = []
                for number, name in enumerate(sorted(old)):
                    if old[name]["maximum"] != new[name]["maximum"]:
                        raise ValueError("MAX_HP_CHANGED")
                    if old[name]["hp"] != new[name]["hp"]:
                        changes.append(
                            {
                                "actor": f"actor_{number}",
                                "before": old[name]["hp"],
                                "after": new[name]["hp"],
                                "maximum": old[name]["maximum"],
                            }
                        )
                if not 1 <= len(changes) <= 5:
                    raise ValueError("NO_HP_CHANGE_OR_TOO_MANY_TARGETS")
                fingerprint = digest(changes)
                if fingerprint in seen:
                    raise ValueError("DUPLICATE_TRANSITION")
                seen.add(fingerprint)
                text = []
                for change in changes:
                    delta = change["after"] - change["before"]
                    text.append(
                        f"Участник {change['actor']}: HP {change['before']} → "
                        f"{change['after']}/{change['maximum']}; "
                        + (f"восстановлено {delta} HP" if delta > 0 else f"потеряно {-delta} HP")
                    )
                answer = "; ".join(text) + "."
                if any(c["after"] == 0 for c in changes):
                    answer += " Смерть при 0 HP этим снимком не подтверждена."
                group["rows"].append(
                    {
                        "schema_version": SCHEMA,
                        "sample_id": "fireball_" + digest([entry["path"], index])[:24],
                        "campaign_id": "",
                        "synthetic": True,
                        "observed_state": True,
                        "human_reviewed": False,
                        "narration_origin": "AUTHORED_RUSSIAN_NOT_HUMAN_TRANSCRIPT",
                        "public_context": {"observed_hp_changes": changes},
                        "player_message": (
                            "Опиши подтверждённое изменение HP, не придумывая причину и смерть."
                        ),
                        "engine_receipt": {
                            "provenance": "FIREBALL_AVRAE_OBSERVED_NOT_DND_NCFU",
                            "changes": changes,
                            "dice": None,
                            "death_confirmed": False,
                        },
                        "assistant_reply": answer,
                        "source": {
                            "dataset": "lara-martin/FIREBALL",
                            "revision": manifest["revision"],
                            "file": entry["path"],
                            "file_sha256": entry["sha256"],
                            "line": index,
                            "line_sha256": hashlib.sha256(line).hexdigest(),
                            "license": "CC-BY-4.0",
                        },
                    }
                )
            except (ValueError, KeyError, TypeError) as error:
                rejected[str(error)] += 1
        groups.append(group)
    # Shared participants connect combats before assigning any split.
    components = []
    for group in groups:
        while True:
            joined = [c for c in components if c["controllers"] & group["controllers"]]
            if not joined:
                break
            for component in joined:
                components.remove(component)
                group["controllers"] |= component["controllers"]
                group["rows"] += component["rows"]
                group["id"] += ":" + component["id"]
        components.append(group)
    components = sorted((c for c in components if c["rows"]), key=lambda c: digest(c["id"]))
    if not components:
        raise ValueError("No eligible FIREBALL transitions")
    parts = {s: [] for s in SPLITS}
    for index, group in enumerate(components):
        split = (
            "train"
            if len(components) < 3
            else "test"
            if index == 0
            else "val"
            if index == 1
            else "train"
        )
        for row in group["rows"]:
            row["campaign_id"] = "fireball_group_" + digest(group["id"])[:24]
            parts[split].append(row)
    return parts, {
        "rejected": dict(rejected),
        "independent_groups": len(components),
        "external_holdout_available": len(components) >= 3,
        "accepted": sum(map(len, parts.values())),
    }


def build(baseline, source, output):
    from training.grounded_validation import verify as verify_baseline

    base, base_parts = verify_baseline(baseline)
    external, report = extract(source)
    output = Path(output)
    output.mkdir(exist_ok=False, parents=True)
    shutil.copytree(baseline, output / "baseline")
    shutil.copytree(source, output / "fireball-source")
    all_rows = []
    for split in SPLITS:
        rows = base_parts[split] + external[split]
        all_rows.extend(rows)
        (output / (split + ".jsonl")).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
        )
    manifest = {
        "dataset_policy": POLICY,
        "status": "READY_FIREBALL_AUGMENTED",
        "sha256": digest(sorted(all_rows, key=lambda r: r["sample_id"])),
        "baseline_sha256": base["sha256"],
        "baseline_samples": 1100,
        "fireball": report,
        "human_reviewed_samples": 0,
        "real_dnd_ncfu_episodes": 0,
        "training_steps": 0,
        "approved_for_runtime": False,
        "file_sha256": {
            s: hashlib.sha256((output / (s + ".jsonl")).read_bytes()).hexdigest() for s in SPLITS
        },
        "splits": {s: len(base_parts[s]) + len(external[s]) for s in SPLITS},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    verify(output)
    return manifest


def verify(directory):
    from training.grounded_validation import verify as verify_baseline

    root = Path(directory)
    m = json.loads((root / "manifest.json").read_text())
    if m.get("dataset_policy") != POLICY or m.get("status") != "READY_FIREBALL_AUGMENTED":
        raise ValueError("Explicit FIREBALL corpus policy required")
    base, original = verify_baseline(root / "baseline")
    external, report = extract(root / "fireball-source")
    if base["sha256"] != m["baseline_sha256"] or report != m["fireball"]:
        raise ValueError("Changed corpus provenance")
    parts = {}
    for split in SPLITS:
        raw = (root / (split + ".jsonl")).read_bytes()
        parts[split] = [json.loads(line) for line in raw.splitlines()]
        if (
            hashlib.sha256(raw).hexdigest() != m["file_sha256"][split]
            or parts[split] != original[split] + external[split]
        ):
            raise ValueError("Changed FIREBALL corpus or split assignment")
    if digest(sorted(sum(parts.values(), []), key=lambda r: r["sample_id"])) != m["sha256"]:
        raise ValueError("Changed corpus digest")
    return m, parts


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.baseline, args.source, args.output), indent=2))


if __name__ == "__main__":
    main()
