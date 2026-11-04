"""Lossless external observations and task candidates; never execute imported commands.

The immutable files are layer A; SQLite compressed original JSON is layer B;
per-task candidates and dispositions are layer C. No human approval is inferred.
"""

import argparse
import base64
import gzip
import hashlib
import json
import math
import re
import sqlite3
import zlib
from collections import Counter, deque
from pathlib import Path

TASKS = (
    "utterance_to_command",
    "command_to_result",
    "observed_transition",
    "grounded_utterance",
    "dialogue_sequence",
    "entity_observation",
    "negative_outcome_candidate",
    "raw_event",
)
ENTITY_FIELDS = {
    "spells",
    "actions",
    "attacks",
    "effects",
    "class",
    "race",
    "items",
    "inventory",
    "resources",
    "conditions",
}


def dumps(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def packed(value):
    return zlib.compress(dumps(value).encode(), 3)


def unpacked(value):
    return json.loads(zlib.decompress(value))


def strict_source_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_source_key:" + key)
            result[key] = value
        return result

    def constant(text):
        raise ValueError("non_json_constant:" + text)

    def finite_float(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("non_finite_number:" + text)
        return value

    return json.loads(
        raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite_float
    )


def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def language(value):
    text = str(value)
    latin = len(re.findall("[A-Za-z]", text))
    cyrillic = len(re.findall("[А-Яа-яЁё]", text))
    return "ru_heuristic" if cyrillic > latin else "en_heuristic" if latin > 10 else "und"


def source_role(record):
    # No inference that a controller or a third-person narrator is the DM.
    if type(record.get("author_bot")) is bool:
        return ("bot" if record["author_bot"] else "human_role_unknown", "explicit_author_bot")
    author = record.get("author")
    if isinstance(author, dict) and type(author.get("bot")) is bool:
        return ("bot" if author["bot"] else "human_role_unknown", "explicit_bot_flag")
    if record.get("event_type") == "automation_run":
        return "automation", "explicit_event_type"
    return "unknown", "not_available_in_source"


def scrub(value):
    """Export-only removal; the original is always retained in layer B."""
    if isinstance(value, dict):
        return {
            k: scrub(v)
            for k, v in value.items()
            if k
            not in {
                "controller_id",
                "speaker_id",
                "author_id",
                "author_name",
                "avatar_url",
                "proxy_url",
            }
        }
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"<@!?\d+>", "[DISCORD_ID]", value)
        value = re.sub(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", "[EMAIL]", value)
        value = re.sub(r"https?://\S+", "[URL]", value)
        value = re.sub(r"(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)", "[NUMBER_REVIEW]", value)
    return value


def field_inventory(value, path="$"):
    yield path, type(value).__name__
    if isinstance(value, dict):
        for key, child in value.items():
            yield from field_inventory(child, path + "." + key)
    elif isinstance(value, list):
        for child in value:
            yield from field_inventory(child, path + "[]")


def entities(value, path="$"):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ENTITY_FIELDS:
                yield path + "." + key, key, child
            yield from entities(child, path + "." + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from entities(child, f"{path}[{index}]")


def task_candidates(record, previous):
    """Task-specific inputs are explicit allowlists; future targets never enter command inputs."""
    commands = record.get("commands_norm")
    results = record.get("automation_results")
    before = record.get("before_utterances")
    after = record.get("after_utterances")
    state_before = record.get("combat_state_before")
    state_after = record.get("combat_state_after")
    prior = {
        k: record[k]
        for k in ("combat_state_before", "current_actor", "utterance_history", "before_utterances")
        if k in record
    }
    available = {}
    if isinstance(commands, list) and commands:
        if isinstance(before, list) and before:
            available["utterance_to_command"] = (
                prior,
                commands,
                "observed_command_role_unverified",
            )
        if isinstance(results, list) and results:
            available["command_to_result"] = (
                prior | {"commands": commands},
                results,
                "bot_automation",
            )
    if isinstance(state_before, list) and isinstance(state_after, list):
        available["observed_transition"] = (
            {
                "before": state_before,
                **{k: record[k] for k in ("commands_norm", "automation_results") if k in record},
            },
            state_after,
            "observed_state_not_universal_rule",
        )
    if isinstance(after, list) and after:
        available["grounded_utterance"] = (
            prior
            | {
                k: record[k]
                for k in ("commands_norm", "automation_results", "combat_state_after")
                if k in record
            },
            after,
            "source_linked_utterance_human_and_dm_role_unverified",
        )
    # History windows are built only AFTER splitting and within this source session.
    if isinstance(before, list) and before:
        available["dialogue_sequence"] = (
            {"previous_turns": list(previous)},
            before,
            "source_utterance_role_unverified",
        )
    found = list(entities(record))
    if found:
        available["entity_observation"] = (
            {"source_scope": "single_observation"},
            [{"path": path, "field": key, "observed": value} for path, key, value in found],
            "observed_entity_not_rule_or_implementation",
        )
    if (
        isinstance(commands, list)
        and commands
        and isinstance(results, list)
        and results
        and re.search(r"\b(error|invalid|not found|cannot|failed)\b", dumps(results), re.I)
    ):
        available["negative_outcome_candidate"] = (
            prior | {"commands": commands},
            results,
            "lexical_candidate_needs_context_review",
        )
    if "event_type" in record:
        available["raw_event"] = (
            {"event_type": record["event_type"]},
            record,
            "source_event_not_human_narration",
        )
    return available


def database(root):
    db = sqlite3.connect(Path(root) / "observations.sqlite", timeout=60)
    db.executescript("""
      PRAGMA journal_mode=WAL;
      CREATE TABLE IF NOT EXISTS observations(
        id TEXT PRIMARY KEY,file TEXT,line INTEGER,line_sha TEXT,group_id TEXT,
        original_session TEXT,kind TEXT,author TEXT,role TEXT,confidence TEXT,
        language TEXT,payload BLOB,exact TEXT,near TEXT,status TEXT,reason TEXT);
      CREATE INDEX IF NOT EXISTS obs_file ON observations(file,line);
      CREATE INDEX IF NOT EXISTS obs_near ON observations(near);
      CREATE TABLE IF NOT EXISTS ingested(file TEXT PRIMARY KEY,sha TEXT,lines INTEGER);
      CREATE TABLE IF NOT EXISTS fields(path TEXT,type TEXT,n INTEGER,PRIMARY KEY(path,type));
      CREATE TABLE IF NOT EXISTS split_map(group_id TEXT PRIMARY KEY,component TEXT,split TEXT);
      CREATE TABLE IF NOT EXISTS views(
        id TEXT PRIMARY KEY,observation_id TEXT,task TEXT,group_id TEXT,split TEXT,
        input BLOB,target BLOB,target_kind TEXT,readiness TEXT,privacy TEXT);
      CREATE TABLE IF NOT EXISTS dispositions(
        observation_id TEXT,task TEXT,status TEXT,reason TEXT,PRIMARY KEY(observation_id,task));
      CREATE TABLE IF NOT EXISTS view_links(
        view_id TEXT,related_observation TEXT,relation TEXT,
        PRIMARY KEY(view_id,related_observation,relation));
      CREATE TABLE IF NOT EXISTS exported(id TEXT PRIMARY KEY,profile INTEGER,status TEXT,
        input_tokens INTEGER,target_tokens INTEGER,total_tokens INTEGER,encoded_sha TEXT);
    """)
    return db


def paged_observations(db, columns, join="", batch_size=256):
    """Release the SELECT cursor before writing a batch so WAL can checkpoint."""
    last_file, last_line = "", 0
    while True:
        batch = db.execute(
            "SELECT o.file,o.line,"
            + columns
            + " FROM observations o "
            + join
            + " WHERE (o.file,o.line)>(?,?) ORDER BY o.file,o.line LIMIT ?",
            (last_file, last_line, batch_size),
        ).fetchall()
        if not batch:
            return
        yield from batch
        last_file, last_line = batch[-1][:2]


def indices(record, key):
    value = record.get(key)
    return [v for v in value if type(v) is int] if isinstance(value, list) else []


def ingest(root):
    root = Path(root)
    db = database(root)
    inventory = json.loads((root / "inventory.json").read_text(encoding="utf-8"))
    expected = {e["path"]: e for e in inventory["entries"] if e["path"].endswith(".jsonl")}
    downloads = sqlite3.connect(root / "downloads.sqlite")
    files = [
        (path, sha)
        for path, sha in downloads.execute(
            "SELECT path,sha256 FROM files WHERE status='OK' ORDER BY path"
        )
    ]
    # The official demonstration is clearly a separate, incomplete raw source.
    for file in ("filtered_triples.jsonl", "raw.jsonl"):
        path = root / "primary/FIREBALL" / file
        if path.exists():
            files.append(("DEMO/" + file, hashlib.sha256(path.read_bytes()).hexdigest()))
    for number, (file, sha) in enumerate(files, 1):
        previous = db.execute("SELECT sha FROM ingested WHERE file=?", (file,)).fetchone()
        if previous:
            if previous[0] != sha:
                raise ValueError("Previously ingested immutable source changed")
            continue
        path = (
            root / "primary/FIREBALL" / file[5:]
            if file.startswith("DEMO/")
            else root / "originals" / file
        )
        total = 0
        actual_hash = hashlib.sha256()
        with path.open("rb") as stream:
            for total, raw in enumerate(stream, 1):
                actual_hash.update(raw)
                identity = digest(
                    [inventory["revision"], file, total, hashlib.sha256(raw).hexdigest()]
                )
                try:
                    value = strict_source_json(raw)
                    if not isinstance(value, dict):
                        raise ValueError("source_record_not_object")
                    canonical = packed(value)
                    if dumps(unpacked(canonical)) != dumps(value):
                        raise ValueError("canonical_roundtrip_mismatch")
                    original_session = next(
                        (
                            value[k]
                            for k in ("campaign_id", "combat_id", "session_id")
                            if k in value and value[k] is not None
                        ),
                        None,
                    )
                    group = (
                        ("explicit:" + dumps(original_session))
                        if original_session is not None
                        else "file:" + file
                    )
                    role, confidence = source_role(value)
                    kind = value.get("event_type", "filtered_turn")
                    # Normalize whole turns; a command alone is not duplicate evidence.
                    signature = {
                        k: v
                        for k, v in value.items()
                        if not k.endswith("_idx")
                        and not k.endswith("_idxs")
                        and k not in {"speaker_id", "timestamp", "created_at", "message_id"}
                    }
                    near = hashlib.sha256(
                        re.sub(r"\s+", " ", dumps(signature).casefold()).encode()
                    ).hexdigest()
                    for (field, typ), count in Counter(field_inventory(value)).items():
                        db.execute(
                            (
                                "INSERT INTO fields VALUES(?,?,?) ON CONFLICT(path,type) DO UPDAT"
                                "E SET n=n+excluded.n"
                            ),
                            (field, typ, count),
                        )
                    status, reason = "PRESERVED", None
                    author = dumps(value.get("speaker_id", value.get("author_id")))
                    lang = language(value.get("before_utterances", value.get("content", "")))
                except Exception as error:
                    value = {"raw_line_base64": base64.b64encode(raw).decode()}
                    canonical = packed(value)
                    original_session, group, role, confidence, kind, near = (
                        None,
                        "file:" + file,
                        "unknown",
                        "unknown",
                        "quarantine",
                        None,
                    )
                    status, reason, author, lang = (
                        "QUARANTINE",
                        type(error).__name__ + ": " + str(error),
                        "null",
                        "und",
                    )
                db.execute(
                    "INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        identity,
                        file,
                        total,
                        hashlib.sha256(raw).hexdigest(),
                        group,
                        dumps(original_session),
                        str(kind),
                        author,
                        role,
                        confidence,
                        lang,
                        canonical,
                        digest(value),
                        near,
                        status,
                        reason,
                    ),
                )
        if actual_hash.hexdigest() != sha:
            db.rollback()
            raise ValueError("Source digest changed during reading")
        db.execute("INSERT INTO ingested VALUES(?,?,?)", (file, sha, total))
        db.commit()
        if number % 25 == 0 or number == len(files):
            print(dumps({"ingested_files": number, "total": len(files)}), flush=True)
    db.close()
    return {"expected_filtered_files": len(expected), "available_files": len(files)}


def assign_splits(db):
    groups = [
        r[0] for r in db.execute("SELECT DISTINCT group_id FROM observations ORDER BY group_id")
    ]
    parent = {g: g for g in groups}

    def find(g):
        while parent[g] != g:
            parent[g] = parent[parent[g]]
            g = parent[g]
        return g

    duplicates = 0
    for (fingerprint,) in db.execute(
        "SELECT near FROM observations WHERE near IS NOT NULL GROUP BY near HAVING COUNT(*)>1"
    ):
        linked = [
            r[0]
            for r in db.execute(
                "SELECT DISTINCT group_id FROM observations WHERE near=?", (fingerprint,)
            )
        ]
        duplicates += 1
        for g in linked[1:]:
            a, b = find(linked[0]), find(g)
            parent[max(a, b)] = min(a, b)
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='duplicate_edges'").fetchone():
        for left, right in db.execute("SELECT a,b FROM duplicate_edges"):
            pair = [
                db.execute("SELECT group_id FROM observations WHERE id=?", (i,)).fetchone()[0]
                for i in (left, right)
            ]
            a, b = find(pair[0]), find(pair[1])
            parent[max(a, b)] = min(a, b)
    # The pinned upstream README states both GitHub demonstration files are one combat.
    # Link this explicit release-level evidence, independently of utterance similarity.
    demo_groups = [
        row[0]
        for row in db.execute(
            "SELECT DISTINCT group_id FROM observations WHERE file IN "
            "('DEMO/raw.jsonl','DEMO/filtered_triples.jsonl')"
        )
    ]
    if len(demo_groups) == 2:
        left, right = (find(g) for g in demo_groups)
        parent[max(left, right)] = min(left, right)
    components = sorted({find(g) for g in groups}, key=lambda s: digest(["split37", s]))
    if len(components) < 3:
        raise ValueError("Not enough independent groups for external holdout")
    n = len(components)
    cut1 = max(1, min(n - 2, int(n * 0.8)))
    cut2 = min(n - 1, max(cut1 + 1, int(n * 0.9)))
    assignments = {
        c: "train" if i < cut1 else "val" if i < cut2 else "test" for i, c in enumerate(components)
    }
    db.execute("DELETE FROM split_map")
    db.executemany(
        "INSERT INTO split_map VALUES(?,?,?)", [(g, find(g), assignments[find(g)]) for g in groups]
    )
    db.commit()
    return {
        "source_groups": len(groups),
        "components": n,
        "normalized_duplicate_clusters": duplicates,
        "explicit_demo_combat_links": 1 if len(demo_groups) == 2 else 0,
        "components_by_split": dict(Counter(assignments.values())),
        ("grouping_limit"): (
            "file proxy when explicit session missing; participant overlap al"
            "one is not campaign proof"
        ),
    }


def load_native_groups(path):
    result = {}
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = strict_source_json(line)
            identity, scope = row["hf_observation_id"], row["native_group"]
            if not isinstance(scope, str) or not scope or identity in result:
                raise ValueError("Invalid or duplicate native group mapping")
            result[identity] = scope
    return result


def trusted_history_scope(file, identity, record, native_groups=None):
    """A physical HF shard may contain many combats; it is never evidence of one history."""
    if native_groups and identity in native_groups:
        return ("native", native_groups[identity])
    for key in ("combat_id", "session_id"):
        if record.get(key) is not None:
            return (key, dumps(record[key]))
    if file == "DEMO/filtered_triples.jsonl":
        return ("pinned_primary_demo", "single_combat_from_upstream_README")
    return None


def build_views(root, native_groups=None):
    from training.fireball_readiness import missing_reason
    from training.fireball_readiness import readiness as task_readiness

    db = database(root)
    if db.execute("SELECT 1 FROM views LIMIT 1").fetchone():
        db.close()
        raise ValueError("Derived views exist; preserve this run and use a new processing root")
    splits = assign_splits(db)
    db.execute("DELETE FROM views")
    db.execute("DELETE FROM dispositions")
    db.execute("DELETE FROM exported")
    db.execute("DELETE FROM view_links")
    db.commit()
    current = None
    history = deque(maxlen=5)
    rows = paged_observations(
        db,
        "o.id,o.group_id,o.payload,o.status,s.split",
        "JOIN split_map s ON s.group_id=o.group_id",
    )
    for index, (file, _line, identity, group, payload, status, split) in enumerate(rows, 1):
        value = unpacked(payload)
        scope = trusted_history_scope(file, identity, value, native_groups)
        if (file, scope) != current or scope is None:
            history.clear()
            current = (file, scope)
        try:
            starts = indices(value, "before_idxs")
            if type(value.get("before_state_idx")) is int:
                starts.append(value["before_state_idx"])
            start = min(starts) if starts else None
            safe_entries = [
                h
                for h in history
                if start is not None and h["end"] is not None and h["end"] < start
            ]
            safe_history = [h["value"] for h in safe_entries]
            candidates = task_candidates(value, safe_history) if status == "PRESERVED" else {}
            error = None
        except Exception as exc:
            candidates = {}
            error = type(exc).__name__ + ": " + str(exc)
        for task in TASKS:
            if task in candidates:
                inputs, target, kind = candidates[task]
                readiness = task_readiness(task, inputs)
                db.execute(
                    "INSERT INTO views VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        digest([identity, task]),
                        identity,
                        task,
                        group,
                        split,
                        packed(scrub(inputs)),
                        packed(scrub(target)),
                        kind,
                        readiness,
                        "AUTOMATED_SCREEN_PENDING_REVIEW",
                    ),
                )
                if task == "dialogue_sequence":
                    db.executemany(
                        "INSERT INTO view_links VALUES(?,?,?)",
                        [
                            (digest([identity, task]), h["id"], "verified_prior_indices")
                            for h in safe_entries
                        ],
                    )
                decision = (
                    "OBSERVATION_ONLY" if readiness.startswith("OBSERVATION_") else "CANDIDATE"
                )
                reason = "source_values; role/privacy review pending; no human approval"
            else:
                decision, reason = "UNAVAILABLE", error or missing_reason(task, value)
                if status != "PRESERVED":
                    reason = "source_parse_quarantine"
            db.execute(
                "INSERT INTO dispositions VALUES(?,?,?,?)", (identity, task, decision, reason)
            )
        # Only prior information is stored; after/results are never history for command prediction.
        if status == "PRESERVED":
            ends = [
                v for k in ("command_idxs", "after_idxs", "embed_idxs") for v in indices(value, k)
            ]
            if type(value.get("after_state_idx")) is int:
                ends.append(value["after_state_idx"])
            history.append(
                {
                    "id": identity,
                    "end": max(ends) if ends else None,
                    "value": {
                        k: value[k] for k in ("before_utterances", "commands_norm") if k in value
                    },
                }
            )
        if index % 1000 == 0:
            db.commit()
            print(dumps({"task_views_records": index}), flush=True)
    db.commit()
    db.close()
    (Path(root) / "history-policy.json").write_text(
        dumps(
            {
                "history_scope_policy": "EXPLICIT_COMBAT_OR_SESSION_OR_VERIFIED_NATIVE_MAP_ONLY",
                "native_mappings": len(native_groups or {}),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return splits


def report(root, split_report):
    root = Path(root)
    db = database(root)

    def counts(query):
        return dict(db.execute(query))

    total = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    dispositions = db.execute("SELECT COUNT(*) FROM dispositions").fetchone()[0]
    lost = db.execute(
        "SELECT COUNT(*) FROM observations o WHERE NOT EXISTS(SELECT 1 FR"
        "OM dispositions d WHERE d.observation_id=o.id)"
    ).fetchone()[0]
    leaks = db.execute(
        "SELECT COUNT(*) FROM views v JOIN split_map s ON s.group_id=v.gr"
        "oup_id WHERE v.split!=s.split"
    ).fetchone()[0]
    sources = [
        {"path": f, "sha256": sha, "lines": n}
        for f, sha, n in db.execute("SELECT * FROM ingested ORDER BY file")
    ]
    fields = [
        {"path": path, "type": typ, "occurrences": n}
        for path, typ, n in db.execute("SELECT * FROM fields ORDER BY path,type")
    ]
    result = {
        "schema": "fireball-complete-observations-v1",
        "observations": total,
        "files_read": len(sources),
        "lines_by_status": counts("SELECT status,COUNT(*) FROM observations GROUP BY status"),
        "event_types": counts("SELECT kind,COUNT(*) FROM observations GROUP BY kind"),
        "source_roles": counts("SELECT role,COUNT(*) FROM observations GROUP BY role"),
        "language_heuristic_not_verified": counts(
            "SELECT language,COUNT(*) FROM observations GROUP BY language"
        ),
        "views_by_task": counts("SELECT task,COUNT(*) FROM views GROUP BY task"),
        "views_by_split": counts("SELECT split,COUNT(*) FROM views GROUP BY split"),
        "dispositions": dispositions,
        "expected_dispositions": total * len(TASKS),
        "unaccounted_records": lost,
        "split_violations": leaks,
        "split_design": split_report,
        "task_decisions": [
            {"task": t, "status": s, "reason": r, "count": n}
            for t, s, r, n in db.execute(
                "SELECT task,status,reason,COUNT(*) FROM dispositions GROUP BY task,status,reason"
            )
        ],
        "field_inventory": fields,
        "sources": sources,
        "human_approved": 0,
        "train_admitted": 0,
        ("runtime_compatibility"): (
            "NOT_REQUIRED_FOR_STORAGE_OR_TASK_CANDIDACY_NOT_IMPLEMENTED_BY_IMPORT"
        ),
        "history_scope_policy": (
            json.loads((root / "history-policy.json").read_text(encoding="utf-8"))[
                "history_scope_policy"
            ]
            if (root / "history-policy.json").exists()
            else None
        ),
        ("canonical_original_fields"): (
            "all original JSON values retained; immutable raw bytes remain layer A"
        ),
        "raw_release": json.loads(
            (
                root / "raw-access-probes.json"
                if (root / "raw-access-probes.json").exists()
                else root / "raw-probe.json"
            ).read_text(encoding="utf-8")
        ),
    }
    (root / "coverage.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    db.close()
    return {
        k: v for k, v in result.items() if k not in {"field_inventory", "sources", "task_decisions"}
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--native-group-map", type=Path)
    a = p.parse_args()
    from training.fireball_audit import refine

    ingest(a.root)
    refine(a.root)
    split = build_views(
        a.root, load_native_groups(a.native_group_map) if a.native_group_map else None
    )
    print(json.dumps(report(a.root, split), indent=2))


if __name__ == "__main__":
    main()
