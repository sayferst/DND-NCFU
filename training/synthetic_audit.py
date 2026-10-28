"""Bounded CPU audit of fictional GM scenes. Never admits rows to real-receipt SFT."""

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from training.schema import validate

PROVENANCE = "SYNTHETIC_SIMULATED_NOT_ENGINE_EXECUTED"


def issues(row):
    found = []
    if (
        row.get("schema_version") != "gm-sft-v1"
        or row.get("synthetic") is not True
        or row.get("review_status") != "pending"
        or row.get("rights_status") != "synthetic_original_unreviewed"
        or row.get("engine_receipt", {}).get("provenance") != PROVENANCE
    ):
        found.append("provenance_or_labels")
    receipt = row.get("engine_receipt", {})
    for roll in receipt.get("rolls", []):
        sides = re.fullmatch(r"d(4|6|8|10|12|20|100)", str(roll.get("die")))
        face = roll.get("face")
        if not sides or type(face) is not int or not 1 <= face <= int(sides[1]):
            found.append("die_range")
            continue
        if roll.get("total") != face + roll.get("modifier", 0):
            found.append("roll_arithmetic")
        if "dc" in roll and roll.get("success") != (roll["total"] >= roll["dc"]):
            found.append("roll_threshold")
    changes = receipt.get("changes", [])
    for change in changes:
        if "before" in change and "after" in change:
            before, after = change["before"], change["after"]
            if type(before) is int and type(after) is int:
                if after < 0:
                    found.append("negative_balance")
                if "delta" in change and after - before != change["delta"]:
                    found.append("change_arithmetic")
    mode = row.get("scene_mode")
    context = row.get("public_context", {})
    if mode in ("trade_buy", "trade_sell"):
        shop = context.get("shop", {})
        cost = shop.get("unit_price_cp", 0) * shop.get("quantity", 0)
        deltas = {c["field"]: c.get("delta", 0) for c in changes}
        sign = -1 if mode == "trade_buy" else 1
        if (
            deltas.get("hero.copper") != sign * cost
            or deltas.get("merchant.copper") != -sign * cost
        ):
            found.append("trade_conservation")
        payer = "hero_copper" if sign == -1 else "merchant_copper"
        if shop.get(payer, 0) < cost:
            found.append("trade_unfunded")
    if mode == "spell_no_mana" and (changes or receipt.get("rolls")):
        found.append("rejected_action_changed_state")
    reply = row.get("assistant_reply", "")
    if re.search(r"(?:флакон|амулет|нож|фонарь|паёк)[^.\n]{0,65}не изготовлена", reply):
        found.append("grammar_gender")
    if re.search(r"(?:вы решили|вы согласились|вы обязаны согласиться)", reply.casefold()):
        found.append("agency_requires_review")
    if "вечер" in context.get("weather", "") and context.get("time", "").startswith(
        ("07", "08", "09")
    ):
        found.append("time_weather_contradiction")
    if mode == "world_event" and any(c.get("field") == "settlement.public_status" for c in changes):
        found.append("world_event_has_no_numeric_stock_receipt")
    return sorted(set(found))


def template(row):
    """Measure compositional reuse after masking known substitutions, not human quality."""
    text = row["assistant_reply"].casefold().replace("ё", "е")
    values = []

    def collect(value):
        if isinstance(value, dict):
            for v in value.values():
                collect(v)
        elif isinstance(value, list):
            for v in value:
                collect(v)
        elif isinstance(value, str) and len(value) >= 3:
            values.append(value.casefold().replace("ё", "е"))

    collect(row["public_context"])
    for value in sorted(set(values), key=len, reverse=True):
        text = text.replace(value, " _ ")
    text = re.sub(r"\d+", "#", text)
    return " ".join(re.findall(r"[а-яa-z_#]+", text))


def audit(path, *, output=None):
    counters, modes, templates, replies = Counter(), Counter(), defaultdict(list), Counter()
    ids, families, rows, samples = set(), set(), [], defaultdict(list)
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for number, raw in enumerate(stream, 1):
            if len(raw) > 128 * 1024 or number > 100000:
                raise ValueError("Synthetic audit size limit exceeded")
            digest.update(raw)
            row = json.loads(raw.decode("utf-8"))
            id, family = row["sample_id"], row["campaign_id"]
            if id in ids:
                raise ValueError("Duplicate synthetic sample ID")
            ids.add(id)
            families.add(family)
            modes[row["scene_mode"]] += 1
            for issue in issues(row):
                counters[issue] += 1
                if len(samples[issue]) < 12:
                    samples[issue].append(id)
            counters["real_pipeline_rejected"] += not validate(row)[0]
            replies[hashlib.sha256(row["assistant_reply"].encode()).hexdigest()] += 1
            key = hashlib.sha256(template(row).encode()).hexdigest()
            templates[key].append((id, family))
            rows.append((id, family, row["scene_mode"]))
    ordered = sorted(families)
    random.Random(20261028).shuffle(ordered)
    a, b = len(ordered) * 8 // 10, len(ordered) * 9 // 10
    parts = {f: "train" if n < a else "val" if n < b else "test" for n, f in enumerate(ordered)}
    cross = sum(len({parts[f] for _, f in values}) > 1 for values in templates.values())
    parent = {f: f for f in families}

    def find(family):
        while parent[family] != family:
            parent[family] = parent[parent[family]]
            family = parent[family]
        return family

    for values in templates.values():
        first = values[0][1]
        for _, family in values[1:]:
            parent[find(family)] = find(first)
    components = Counter(find(f) for f in families)
    report = {
        "schema": "synthetic-gm-audit-1",
        "source_sha256": digest.hexdigest(),
        "records": len(rows),
        "unique_ids": len(ids),
        "families": len(families),
        "modes": dict(modes),
        "issues": dict(counters),
        "issue_examples": dict(samples),
        "unique_reply_hashes": len(replies),
        "normalized_templates": len(templates),
        "templates_shared_between_splits": cross,
        "group_overlap": 0,
        "template_connected_components": len(components),
        "largest_component_families": max(components.values(), default=0),
        "independent_three_way_split_possible": len(components) >= 3,
        "proposed_split_counts": dict(Counter(parts[f] for _, f, _ in rows)),
        "split_ids": {
            p: [id for id, f, _ in rows if parts[f] == p] for p in ("train", "val", "test")
        },
        "source_labels_modified": False,
        "admitted_real_sft": 0,
        "training_started": False,
        "production_ready": False,
        "limitations": (
            "Static arithmetic and reuse checks, not human review or engine verification. "
            "Family-disjoint proposal is not a leakage-free training release "
            "when templates cross splits."
        ),
    }
    if output:
        with Path(output).open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.input, output=args.output)
    print(json.dumps({k: v for k, v in result.items() if k != "split_ids"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
