"""Independent readiness and accounting refinements; preserve all stored observations/views."""

import argparse
import hashlib
import json
from pathlib import Path

from training.fireball_observations import database, paged_observations, unpacked


def readiness(task, inputs):
    if task in {"entity_observation", "raw_event"}:
        return "OBSERVATION_VIEW_NOT_SFT_PAIR"
    if task == "dialogue_sequence" and not inputs.get("previous_turns"):
        return "OBSERVATION_CONTEXT_INSUFFICIENT_RETAINED"
    if task in {"grounded_utterance", "observed_transition"} and not inputs.get(
        "automation_results"
    ):
        return "OBSERVATION_CONFIRMED_RESULTS_ABSENT_RETAINED"
    return "STRUCTURAL_CANDIDATE_NOT_HUMAN_APPROVED"


def missing_reason(task, record):
    required = {
        "utterance_to_command": ("commands_norm", "before_utterances"),
        "command_to_result": ("commands_norm", "automation_results"),
        "observed_transition": ("combat_state_before", "combat_state_after"),
        "grounded_utterance": ("after_utterances",),
        "dialogue_sequence": ("before_utterances",),
        "negative_outcome_candidate": ("commands_norm", "automation_results"),
    }
    if task == "raw_event":
        return "event_type_absent"
    if task == "entity_observation":
        return "no_recognized_entity_field_in_nested_source_original_still_preserved"
    problems = []
    for field in required[task]:
        if field not in record:
            problems.append(field + ":absent")
        elif not isinstance(record[field], list):
            problems.append(field + ":not_list")
        elif not record[field] and task != "observed_transition":
            problems.append(field + ":empty")
    if problems:
        return ";".join(problems)
    return "no_lexical_negative_evidence_interpretation_not_inferred"


def reconcile(root):
    """Keyset batches release read cursors before mutations and checkpoint naturally."""
    db = database(root)
    changed = 0
    for i, (_file, _line, identity, payload, status) in enumerate(
        paged_observations(db, "o.id,o.payload,o.status"), 1
    ):
        for task, inp, kind in db.execute(
            "SELECT task,input,target_kind FROM views WHERE observation_id=?", (identity,)
        ).fetchall():
            # Existing views have an index on id, not observation_id; see index below.
            ready = readiness(task, unpacked(inp))
            if ready != "STRUCTURAL_CANDIDATE_NOT_HUMAN_APPROVED":
                db.execute(
                    "UPDATE views SET readiness=? WHERE observation_id=? AND task=?",
                    (ready, identity, task),
                )
                db.execute(
                    "UPDATE dispositions SET status='OBSERVATION_ONLY',reason=? "
                    "WHERE observation_id=? AND task=?",
                    (ready, identity, task),
                )
                changed += 1
            if kind == "observed_human_command":
                db.execute(
                    "UPDATE views SET target_kind='observed_command_role_unverified' "
                    "WHERE observation_id=? AND task=?",
                    (identity, task),
                )
        if status == "PRESERVED":
            value = unpacked(payload)
            for (task,) in db.execute(
                "SELECT task FROM dispositions WHERE observation_id=? AND status='UNAVAILABLE'",
                (identity,),
            ).fetchall():
                db.execute(
                    "UPDATE dispositions SET reason=? WHERE observation_id=? AND task=?",
                    (missing_reason(task, value), identity, task),
                )
        if i % 1000 == 0:
            db.commit()
        if i % 20000 == 0:
            print(json.dumps({"readiness_observations": i}), flush=True)
    db.commit()
    db.close()
    return changed


def audit_links(root):
    db = database(root)
    leakage = db.execute(
        "SELECT COUNT(*) FROM view_links l JOIN views v ON v.id=l.view_id "
        "JOIN observations o ON o.id=l.related_observation JOIN split_map s "
        "ON s.group_id=o.group_id WHERE v.split!=s.split OR v.group_id!=o.group_id"
    ).fetchone()[0]
    source_leaks = db.execute(
        "SELECT COUNT(*) FROM views v JOIN observations o ON o.id=v.observation_id "
        "JOIN split_map s ON s.group_id=o.group_id WHERE v.split!=s.split OR v.group_id!=o.group_id"
    ).fetchone()[0]
    result = {
        "history_links": db.execute("SELECT COUNT(*) FROM view_links").fetchone()[0],
        "history_cross_split_or_group": leakage,
        "view_source_split_or_group_mismatch": source_leaks,
        "source_by_split": [
            dict(zip(("source", "split", "records"), row, strict=True))
            for row in db.execute(
                "SELECT CASE WHEN file LIKE 'filtered/%' THEN 'HF_FILTERED' "
                "ELSE file END,s.split,COUNT(*) FROM observations o JOIN "
                "split_map s ON s.group_id=o.group_id GROUP BY 1,2"
            )
        ],
        "view_readiness": [
            dict(zip(("task", "readiness", "n"), row, strict=True))
            for row in db.execute("SELECT task,readiness,COUNT(*) FROM views GROUP BY 1,2")
        ],
        "independent_axes": {
            "preservation": "observations.status/reason",
            "provenance": "source_metadata",
            "task_eligibility": "dispositions and views.readiness",
            "review": "NO_HUMAN_APPROVAL",
            "privacy": "REDACTED_DERIVATIVES_PENDING_CONTENT_REVIEW_LOCAL_RESTRICTED",
            "rights": "SOURCE_CC_BY_4_0_ATTRIBUTION_CONTENT_RIGHTS_REVIEW_PENDING",
            "runtime": "NOT_ASSESSED_NOT_REQUIRED_FOR_STORAGE_OR_CANDIDACY",
        },
    }
    snapshot = hashlib.sha256()
    last = ""
    while rows := db.execute(
        "SELECT id,input,target FROM views WHERE id>? ORDER BY id LIMIT 256", (last,)
    ).fetchall():
        for identity, inputs, target in rows:
            snapshot.update(identity.encode())
            snapshot.update(hashlib.sha256(inputs).digest())
            snapshot.update(hashlib.sha256(target).digest())
        last = rows[-1][0]
    result["views_input_target_sha256"] = snapshot.hexdigest()
    db.close()
    (Path(root) / "readiness-and-leakage.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    db = database(a.root)
    db.execute("CREATE INDEX IF NOT EXISTS views_source ON views(observation_id,task)")
    db.commit()
    db.close()
    reconcile(a.root)
    print(json.dumps(audit_links(a.root), indent=2))


if __name__ == "__main__":
    main()
