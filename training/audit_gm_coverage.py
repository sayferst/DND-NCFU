"""Audit every source record against requested domains without inventing training approval."""

import argparse
import gzip
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

from training.crd3_source import read_sources
from training.fireball_observations import unpacked
from training.gm_mechanics import MECHANICS, fireball_evidence, prose_evidence, reference_evidence


def audit(fireball_root, crd3_root, baseline_root, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    counts, roles = Counter(), Counter()
    domains = {key: Counter() for key in MECHANICS}
    db = sqlite3.connect(
        (Path(fireball_root) / "observations.sqlite").resolve().as_uri() + "?mode=ro", uri=True
    )
    ledger = output / "source-domain-ledger.jsonl.gz"

    def account(stream, identity, source, tags, **metadata):
        counts[source] += 1
        for key, evidence in tags.items():
            domains[key][source + ":" + evidence] += 1
        stream.write(
            json.dumps(
                {"id": identity, "source": source, "evidence": tags, **metadata},
                ensure_ascii=True,
                separators=(",", ":"),
            )
            + "\n"
        )

    with gzip.open(ledger, "wt", encoding="utf-8", compresslevel=6) as stream:
        for identity, file, line, payload in db.execute(
            "SELECT id,file,line,payload FROM observations WHERE file LIKE 'filtered/%' "
            "AND status='PRESERVED' ORDER BY file,line"
        ):
            account(
                stream,
                identity,
                "FIREBALL_FILTERED",
                fireball_evidence(unpacked(payload)),
                file=file,
                line=line,
            )
        db.close()
        for entry, value in read_sources(crd3_root):
            turns = value.get("TURNS")
            if not isinstance(turns, list):
                raise ValueError("Unknown CRD3 turn schema")
            for index, turn in enumerate(turns):
                names = turn.get("NAMES")
                role = "DM_EXPLICIT_MATT" if names == ["MATT"] else "OTHER_OR_MULTIPLE_SPEAKERS"
                roles[role] += 1
                utterances = turn.get("UTTERANCES")
                text = (
                    " ".join(utterances)
                    if isinstance(utterances, list) and all(isinstance(t, str) for t in utterances)
                    else ""
                )
                tags = prose_evidence(text) if text and role == "DM_EXPLICIT_MATT" else {}
                if text and role == "DM_EXPLICIT_MATT":
                    tags["narration"] = "SOURCE_DM_TRANSCRIPT_REQUIRES_CONTENT_SCREENING"
                    if '"' in text:
                        tags["npc_dialogue"] = "POSSIBLE_QUOTED_DIALOGUE_NOT_CHARACTER_ROLE_PROOF"
                account(
                    stream,
                    entry["path"] + ":" + str(index),
                    "CRD3_TRANSCRIPT",
                    tags,
                    role=role,
                    original_turn_number=turn.get("NUMBER"),
                )
        from training.grounded_validation import verify

        _, parts = verify(baseline_root)
        for split, rows in parts.items():
            for row in rows:
                account(
                    stream,
                    row["sample_id"],
                    "SYNTHETIC_REFERENCE",
                    reference_evidence(row),
                    split=split,
                )
    gaps = []
    source_only_prose = []
    for key, values in domains.items():
        if not values:
            gaps.append(key)
        elif all(
            "NARRATIVE_MENTION" in evidence or "POSSIBLE_" in evidence
            for evidence in values
            if not evidence.startswith("SYNTHETIC_REFERENCE:")
        ):
            source_only_prose.append(key)
    report = {
        "schema": "gm-domain-coverage-v1",
        "status": "COMPLETE_SOURCE_INVENTORY_NOT_MODEL_QUALITY_VERDICT",
        "records": dict(counts),
        "crd3_speaker_roles": dict(roles),
        "requested_domains": len(MECHANICS),
        "domains": {
            key: {"description": MECHANICS[key], "counts": dict(value)}
            for key, value in domains.items()
        },
        "no_evidence_domains": gaps,
        "no_strong_source_evidence_domains": source_only_prose,
        "ledger_sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
        "notes": [
            "Narrative mentions are not executed mechanics or validated rules.",
            "Character-sheet repertoire is excluded from execution counts.",
            "A source account/role does not imply local human approval.",
            "No source data or old splits were modified.",
        ],
        "human_approved": 0,
        "train_admitted": 0,
        "training_steps": 0,
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fireball-root", required=True, type=Path)
    parser.add_argument("--crd3-root", required=True, type=Path)
    parser.add_argument("--baseline-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit(args.fireball_root, args.crd3_root, args.baseline_root, args.output)
    print(
        json.dumps(
            {k: report[k] for k in ("status", "records", "no_evidence_domains", "training_steps")}
        )
    )


if __name__ == "__main__":
    main()
