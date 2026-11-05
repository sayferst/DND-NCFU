"""Complete provenance, entity surface inventory and duplicate evidence; no rules inferred."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from training.fireball_observations import (
    database,
    digest,
    dumps,
    entities,
    paged_observations,
    scrub,
    source_role,
    unpacked,
)


def surfaces(value):
    if isinstance(value, str):
        depth = 0
        start = 0
        for i, char in enumerate(value):
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif char == "," and not depth:
                if value[start:i].strip():
                    yield value[start:i].strip()
                start = i + 1
        if value[start:].strip():
            yield value[start:].strip()
    elif isinstance(value, list):
        for child in value:
            yield from surfaces(child)
    elif isinstance(value, dict) and isinstance(value.get("name"), str):
        yield value["name"]


def core_signature(value):
    core = {
        k: value[k]
        for k in (
            "before_utterances",
            "combat_state_before",
            "commands_norm",
            "automation_results",
            "combat_state_after",
            "after_utterances",
        )
        if k in value
    }
    if not core:
        core = {
            k: v for k, v in value.items() if k not in {"message_id", "timestamp", "created_at"}
        }
    return hashlib.sha256(re.sub(r"\s+", " ", dumps(scrub(core)).casefold()).encode()).hexdigest()


def refine(root):
    root = Path(root)
    db = database(root)
    db.executescript("""
      CREATE TABLE IF NOT EXISTS source_metadata(file TEXT PRIMARY KEY,payload TEXT);
      CREATE TABLE IF NOT EXISTS entity_inventory(kind TEXT,surface TEXT,occurrences INTEGER,
        first_observation TEXT,first_path TEXT,PRIMARY KEY(kind,surface));
      CREATE TABLE IF NOT EXISTS duplicate_edges(a TEXT,b TEXT,method TEXT,score REAL,
        PRIMARY KEY(a,b,method));
    """)
    inv = json.loads((root / "inventory.json").read_text(encoding="utf-8"))
    gh = json.loads((root / "FIREBALL-tree.json").read_text(encoding="utf-8"))
    for table in ("source_metadata", "entity_inventory", "duplicate_edges"):
        db.execute("DELETE FROM " + table)
    files = db.execute("SELECT * FROM ingested").fetchall()
    for file, sha, n in files:
        demo = file.startswith("DEMO/")
        meta = {
            "source": "zhudotexe/FIREBALL demonstration"
            if demo
            else "lara-martin/FIREBALL filtered",
            "revision": gh["revision"] if demo else inv["revision"],
            "file": file,
            "file_sha256": sha,
            "lines": n,
            "mechanics_source": "Avrae observed; not universal rule",
            "access": "LOCAL_RESTRICTED",
            "license": "CC-BY-4.0",
            "source_url": (
                f"https://raw.githubusercontent.com/zhudotexe/FIREBALL/{gh['revision']}/{file[5:]}"
                if demo
                else f"https://huggingface.co/datasets/lara-martin/FIREBALL/resolve/{inv['revision']}/{file}"
            ),
        }
        db.execute("INSERT INTO source_metadata VALUES(?,?)", (file, dumps(meta)))
    db.commit()
    counts = Counter()
    first = {}
    field_count = 0
    refs = 0
    for i, (_, _, identity, payload, status) in enumerate(
        paged_observations(db, "o.id,o.payload,o.status"), 1
    ):
        if status != "PRESERVED":
            continue
        value = unpacked(payload)
        role, confidence = source_role(value)
        db.execute(
            "UPDATE observations SET role=?,confidence=?,near=? WHERE id=?",
            (role, confidence, core_signature(value), identity),
        )
        for path, kind, child in entities(value):
            field_count += 1
            for surface in surfaces(child):
                key = kind, surface
                counts[key] += 1
                first.setdefault(key, (identity, path))
        for key, v in value.items():
            if key.endswith("_idx") or key.endswith("_idxs"):
                refs += sum(type(x) is int for x in (v if isinstance(v, list) else [v]))
        if i % 1000 == 0:
            db.commit()
            if i % 10000 == 0:
                print(dumps({"audit_records": i}), flush=True)
    db.executemany(
        "INSERT INTO entity_inventory VALUES(?,?,?,?,?)",
        [(kind, surface, n, *first[kind, surface]) for (kind, surface), n in counts.items()],
    )
    db.commit()
    buckets = {}
    tested = set()
    compares = 0
    edges = 0
    for i, (_, _, identity, group, payload, status) in enumerate(
        paged_observations(db, "o.id,o.group_id,o.payload,o.status"), 1
    ):
        if status != "PRESERVED":
            continue
        value = unpacked(payload)
        words = re.findall(
            r"\w+",
            dumps([value.get("before_utterances"), value.get("after_utterances")]).casefold(),
        )
        if len(words) < 16:
            continue
        shingles = {" ".join(words[j : j + 3]) for j in range(len(words) - 2)}
        if len(shingles) < 12:
            continue
        actors = value.get("combat_state_before")
        roster = (
            [
                {k: a.get(k) for k in ("name", "class", "race")}
                for a in actors
                if isinstance(a, dict)
            ]
            if isinstance(actors, list)
            else []
        )
        scope = digest([roster, value.get("commands_norm")])
        for band, seed in enumerate((b"near0001", b"near0002")):
            sketch = min(
                hashlib.blake2s(s.encode(), digest_size=8, person=seed).digest() for s in shingles
            )
            key = scope, band, sketch
            prior = buckets.get(key)
            if prior and prior[1] != group:
                other, _, other_words = prior
                pair = tuple(sorted((identity, other)))
                if pair in tested:
                    continue
                tested.add(pair)
                compares += 1
                score = len(shingles & other_words) / len(shingles | other_words)
                if score >= 0.95:
                    db.execute(
                        "INSERT OR IGNORE INTO duplicate_edges VALUES(?,?,?,?)",
                        (*pair, "trigram_jaccard_same_roster_commands", score),
                    )
                    edges += 1
            else:
                buckets.setdefault(key, (identity, group, shingles))
        if i % 1000 == 0:
            db.commit()
    db.commit()
    demos = []
    for identity, near in db.execute(
        "SELECT id,near FROM observations WHERE file='DEMO/filtered_triples.jsonl'"
    ).fetchall():
        matches = [
            {"id": i, "file": f, "line": line}
            for i, f, line in db.execute(
                "SELECT id,file,line FROM observations WHERE near=? AND file LIKE 'filtered/%'",
                (near,),
            )
        ]
        demos.append({"demo_observation": identity, "full_filtered_matches": matches})
    report = {
        "entity_fields_observed": field_count,
        "native_event_references": refs,
        ("surface_extraction"): (
            "candidate names at top-level commas; raw values retained, not spell definitions"
        ),
        "entity_inventory": [
            {"kind": kind, "distinct_surface_forms": n, "occurrences": total}
            for kind, n, total in db.execute(
                "SELECT kind,COUNT(*),SUM(occurrences) FROM entity_inventory GROUP BY kind"
            )
        ],
        ("reference_resolution"): (
            "source indices retained; full raw release required to resolve full filtered references"
        ),
        "demo_comparison": demos,
        "approximate_comparisons": compares,
        "approximate_edges": edges,
        ("approximate_method"): (
            "two min-trigram bands; Jaccard>=0.95 with identical roster and c"
            "ommands; not exhaustive semantic equivalence"
        ),
        "participant_grouping": "participant overlap alone is not campaign proof",
        "unknown_mechanics_preserved": True,
        "runtime_implemented_by_import": False,
    }
    (root / "extended-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    db.close()
    resolve_demo_references(root)
    return report


def resolve_demo_references(root):
    """Use only the explicitly paired primary demo; do not infer HF raw from a near copy."""
    db = database(root)
    raw = db.execute(
        "SELECT id,payload FROM observations WHERE file='DEMO/raw.jsonl' ORDER BY line"
    ).fetchall()
    db.execute(
        "CREATE TABLE IF NOT EXISTS event_references(observation_id TEXT,field TEXT,"
        "ordinal INTEGER,"
        "native_index INTEGER,event_observation_id TEXT,role TEXT,evidence TEXT,status TEXT,"
        "PRIMARY KEY(observation_id,field,ordinal))"
    )
    db.execute("DELETE FROM event_references")
    counts = Counter()
    utterances = Counter()
    for identity, payload in db.execute(
        "SELECT id,payload FROM observations WHERE file='DEMO/filtered_triples.jsonl' ORDER BY line"
    ).fetchall():
        value = unpacked(payload)
        for field, values in value.items():
            if not (field.endswith("_idx") or field.endswith("_idxs")):
                continue
            for ordinal, index in enumerate(values if isinstance(values, list) else [values]):
                event_id, role, evidence, status = (
                    None,
                    "unknown",
                    "not_resolved",
                    "INDEX_UNAVAILABLE",
                )
                if type(index) is int and 0 <= index < len(raw):
                    event_id, blob = raw[index]
                    event = unpacked(blob)
                    role, evidence = source_role(event)
                    expected = (
                        "message"
                        if field in {"before_idxs", "after_idxs", "embed_idxs"}
                        else (
                            "combat_state_update"
                            if field in {"before_state_idx", "after_state_idx"}
                            else None
                        )
                    )
                    status = (
                        "INDEX_AND_TYPE_CONFIRMED"
                        if expected is None or event.get("event_type") == expected
                        else "INDEX_TYPE_MISMATCH_REVIEW"
                    )
                    if field == "after_idxs" and status == "INDEX_AND_TYPE_CONFIRMED":
                        utterances[role] += 1
                counts[status] += 1
                db.execute(
                    "INSERT INTO event_references VALUES(?,?,?,?,?,?,?,?)",
                    (identity, field, ordinal, index, event_id, role, evidence, status),
                )
    db.commit()
    db.close()
    result = {
        "schema": "fireball-primary-demo-reference-resolution-v1",
        "raw_events_available": len(raw),
        "references": dict(counts),
        "linked_after_utterance_event_roles": dict(utterances),
        "scope": "Only both files in pinned GitHub demo; no automatic HF binding by similarity",
        "dm_role": "NOT_AVAILABLE_NOT_INFERRED_FROM_HUMAN_FLAG",
        "human_approved": 0,
    }
    (Path(root) / "demo-reference-resolution.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def observation(root, identity):
    db = database(root)
    row = db.execute(
        (
            "SELECT file,line,line_sha,group_id,original_session,role,confide"
            "nce,language,payload,status,reason FROM observations WHERE id=?"
        ),
        (identity,),
    ).fetchone()
    if row is None:
        raise KeyError(identity)
    file, line, sha, group, session, role, confidence, lang, payload, status, reason = row
    source = json.loads(
        db.execute("SELECT payload FROM source_metadata WHERE file=?", (file,)).fetchone()[0]
    )
    result = {
        "id": identity,
        "source": source | {"line": line, "line_sha256": sha},
        "source_session_id": json.loads(session),
        "split_group": group,
        "author_role": role,
        "role_evidence": confidence,
        "language_heuristic": lang,
        "status": status,
        "reason": reason,
        "original": unpacked(payload),
        "review": "NOT_HUMAN_APPROVED",
        "runtime": "EXTERNAL_NOT_ASSESSED",
        "rights": "SOURCE_CC_BY_4_0_RESEARCH_CONTENT_RIGHTS_REVIEW_PENDING",
        "privacy": "ORIGINAL_RESTRICTED_PENDING_REVIEW",
    }
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='event_references'").fetchone():
        result["resolved_event_links"] = [
            dict(
                zip(
                    (
                        "field",
                        "ordinal",
                        "native_index",
                        "event_observation_id",
                        "role",
                        "role_evidence",
                        "status",
                    ),
                    row,
                    strict=True,
                )
            )
            for row in db.execute(
                "SELECT field,ordinal,native_index,event_observation_id,role,evidence,status "
                "FROM event_references WHERE observation_id=? ORDER BY field,ordinal",
                (identity,),
            )
        ]
    db.close()
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    action = p.add_mutually_exclusive_group(required=True)
    action.add_argument("--refine", action="store_true")
    action.add_argument("--observation")
    action.add_argument("--view")
    action.add_argument("--resolve-demo", action="store_true")
    a = p.parse_args()
    if a.resolve_demo:
        result = resolve_demo_references(a.root)
    elif a.observation:
        result = observation(a.root, a.observation)
    elif a.view:
        db = database(a.root)
        row = db.execute(
            "SELECT observation_id,task,split,input,target,target_kind,readiness,privacy "
            "FROM views WHERE id=?",
            (a.view,),
        ).fetchone()
        db.close()
        if row is None:
            raise KeyError(a.view)
        result = dict(
            zip(
                (
                    "source_observation_id",
                    "task",
                    "split",
                    "input",
                    "target",
                    "target_kind",
                    "readiness",
                    "privacy",
                ),
                row,
                strict=True,
            )
        )
        result["input"] = unpacked(result["input"])
        result["target"] = unpacked(result["target"])
    else:
        result = refine(a.root)
        result = {k: v for k, v in result.items() if k != "demo_comparison"}
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
