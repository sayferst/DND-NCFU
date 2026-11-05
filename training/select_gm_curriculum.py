"""Select a source-majority curriculum and export complete, self-contained source cases."""

import argparse
import gzip
import hashlib
import json
import math
import shutil
import sqlite3
from collections import Counter, defaultdict, deque
from pathlib import Path

from training.crd3_source import Episodes
from training.fireball_observations import dumps, unpacked
from training.gm_source_pool import identity, materialize_context
from training.source_gm_curation import clean_source_text

RARE_DOMAINS = (
    "crafting",
    "repair",
    "unconventional_item_use",
    "persuasion_negotiation",
    "npc_interests_conflict",
    "trade_economy",
    "world_memory",
    "exploration",
    "rest_exhaustion",
    "scene_quest_generation",
    "npc_dialogue",
    "clarification",
)


def tags_value(value):
    return unpacked(value) if isinstance(value, bytes) else json.loads(value)


def context_contains(value, target):
    if isinstance(value, str):
        return target in clean_source_text(value)
    if isinstance(value, dict):
        return any(context_contains(v, target) for v in value.values())
    if isinstance(value, list):
        return any(context_contains(v, target) for v in value)
    return False


def diversified(rows, quota):
    """Coverage and episode diversity, not an invented human quality score."""
    rows = sorted(rows, key=lambda row: identity([37, row[0]]))
    selected = set()
    for domain in RARE_DOMAINS:
        episodes = set()
        for key, episode, tags in rows:
            if len(selected) >= quota:
                return selected
            if domain in tags and episode not in episodes:
                selected.add(key)
                episodes.add(episode)
                if len(episodes) >= 40:
                    break
    by_episode = defaultdict(deque)
    for key, episode, _ in rows:
        if key not in selected:
            by_episode[episode].append(key)
    while by_episode and len(selected) < quota:
        for episode in sorted(tuple(by_episode)):
            if len(selected) == quota:
                break
            selected.add(by_episode[episode].popleft())
            if not by_episode[episode]:
                del by_episode[episode]
    return selected


def export(pool_root, crd3_root, output, *, release_working_cache=False):
    pool_root, output = Path(pool_root), Path(output)
    report = json.loads((pool_root / "report.json").read_text(encoding="utf-8"))
    if report.get("status") != "CURATION_COMPLETE_SELECTION_PENDING":
        raise ValueError("Complete the entire source curation pass before selection")
    output.mkdir(parents=True, exist_ok=False)
    db = sqlite3.connect((pool_root / "pool.sqlite").as_uri() + "?mode=ro", uri=True)
    selected = {
        row[0]
        for row in db.execute(
            "SELECT id FROM cases WHERE source IN ('FIREBALL','PROJECT_REFERENCE')"
        )
    }
    quotas = {}
    for split in ("train", "val", "test"):
        count = db.execute(
            "SELECT COUNT(*) FROM cases WHERE source='FIREBALL' AND split=?", (split,)
        ).fetchone()[0]
        quota = math.floor(count * 0.4)
        rows = [
            (key, unit.split(":")[0], tags_value(tags))
            for key, unit, tags in db.execute(
                "SELECT id,unit,tags FROM cases WHERE source='CRD3' AND split=? ORDER BY id",
                (split,),
            )
        ]
        chosen = diversified(rows, quota)
        selected.update(chosen)
        quotas[split] = {
            "fireball_candidates": count,
            "crd3_quota": quota,
            "crd3_selected": len(chosen),
        }
    episodes = Episodes(crd3_root)
    source_counts, counts, dropped, domains = Counter(), Counter(), Counter(), defaultdict(Counter)
    output_path = output / "selected-cases.jsonl.gz"
    index_path = output / "all-candidates-index.jsonl.gz"
    digest = hashlib.sha256()
    all_ids, kept = set(), set()

    def guard():
        size = sum(p.stat().st_size for p in output.glob("*.gz"))
        if size > 64 * 1024**2 or shutil.disk_usage(output).free < 192 * 1024**2:
            raise OSError("CURRICULUM_EXPORT_STORAGE_RESERVE_REACHED")

    with (
        gzip.open(output_path, "wt", encoding="utf-8", compresslevel=6) as dest,
        gzip.open(index_path, "wt", encoding="utf-8", compresslevel=6) as index,
    ):
        for number, row in enumerate(
            db.execute(
                "SELECT id,source,group_id,split,unit,rank,context,target,metadata,tags "
                "FROM cases ORDER BY id"
            ),
            1,
        ):
            key, source, group, split, unit, rank, ctx, target, meta, tags = row
            all_ids.add(key)
            proof, text, labels = unpacked(meta), unpacked(target), tags_value(tags)
            why = "SUPPLEMENTARY_POOL_RETAINED_OUTSIDE_PRIMARY_MIX"
            if key in selected:
                context = materialize_context(unpacked(ctx), proof, episodes)
                if source != "PROJECT_REFERENCE" and context_contains(context, text):
                    dropped["EXACT_TARGET_PRESENT_IN_CONTEXT"] += 1
                    why = "EXACT_TARGET_PRESENT_IN_CONTEXT_REVIEW"
                else:
                    value = {
                        "id": key,
                        "source": source,
                        "group_id": group,
                        "split": split,
                        "source_unit": unit,
                        "context": context,
                        "target": text,
                        "provenance": proof,
                        "mechanics_evidence": labels,
                        "human_reviewed": False,
                    }
                    line = dumps(value) + "\n"
                    digest.update(line.encode())
                    dest.write(line)
                    kept.add(key)
                    why = "SELECTED_PENDING_BILINGUAL_AND_OWNER_SAMPLE_CHECK"
                    source_counts[source] += 1
                    counts[split] += 1
                    for domain, evidence in labels.items():
                        domains[domain][source + ":" + evidence] += 1
            index.write(
                dumps(
                    {
                        "id": key,
                        "source": source,
                        "group_id": group,
                        "split": split,
                        "unit": unit,
                        "file": proof.get("file"),
                        "turn": proof.get("turn_index"),
                        "span": proof.get("normalized_span"),
                        "target_sha256": identity(text),
                        "context_sha256": proof.get("context_sha256"),
                        "mechanics_evidence": labels,
                        "disposition": why,
                    }
                )
                + "\n"
            )
            if number % 1000 == 0:
                guard()
    db.close()
    actual, found = hashlib.sha256(), set()
    with gzip.open(output_path, "rb") as stream:
        for line in stream:
            value = json.loads(line)
            if value["id"] in found:
                raise ValueError("Duplicate source case in self-contained export")
            found.add(value["id"])
            actual.update(line)
    if found != kept or actual.hexdigest() != digest.hexdigest():
        raise ValueError("Export reconstruction differs from selected source cases")
    with gzip.open(index_path, "rt", encoding="utf-8") as stream:
        index_ids = {json.loads(line)["id"] for line in stream}
    if index_ids != all_ids:
        raise ValueError("Candidate accounting lost records")
    final = {
        "schema": "gm-source-curriculum-selection-v1",
        "status": "SELECTED_SOURCE_CASES_VERIFIED_TRANSLATION_PENDING",
        "source_counts": dict(source_counts),
        "splits": dict(counts),
        "all_candidate_views": len(all_ids),
        "selected_views": len(kept),
        "supplementary_mix_quotas": quotas,
        "review_dropped": dict(dropped),
        "source_majority_policy": (
            "ALL_ELIGIBLE_FIREBALL_PLUS_REFERENCE_MAX_40_PERCENT_SUPPLEMENTARY_PER_SPLIT"
        ),
        "mechanics_evidence": {key: dict(values) for key, values in domains.items()},
        "selected_uncompressed_sha256": digest.hexdigest(),
        "files": {
            p.name: {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in (output_path, index_path)
        },
        "human_reviewed_samples": 0,
        "training_steps": 0,
    }
    (output / "report.json").write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    if release_working_cache:
        # This cache is a deterministic duplicate of pinned source data plus the
        # now-verified complete candidate index. No source snapshot is removed.
        for suffix in ("-wal", "-shm", "-journal"):
            if Path(str(pool_root / "pool.sqlite") + suffix).exists():
                raise ValueError("Do not release a cache with a live or pending journal")
        (pool_root / "cache-release.json").write_text(
            json.dumps(
                {
                    "reason": "VERIFIED_SELECTED_EXPORT_AND_COMPLETE_CANDIDATE_INDEX_RETAINED",
                    "source_snapshots_removed": False,
                    "cache_bytes": (pool_root / "pool.sqlite").stat().st_size,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (pool_root / "pool.sqlite").unlink()
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool-root", type=Path, required=True)
    parser.add_argument("--crd3-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-working-cache", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            export(
                args.pool_root,
                args.crd3_root,
                args.output,
                release_working_cache=args.release_working_cache,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
