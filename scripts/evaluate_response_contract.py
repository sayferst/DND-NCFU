"""Replay the frozen authored response corpus. No model, network or user save access."""

import argparse
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]


def evaluate():
    from response_cases import context_for, prepare, response

    from rpg_vkr.narrative.context import build_frame
    from rpg_vkr.narrative.story import story_proposal, story_text
    from rpg_vkr.narrative.story_quality import check_story_quality

    path = ROOT / "docs/evals/master-response-2026-10-20/cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    results = []
    for case in cases:
        session = prepare(case)
        before = deepcopy(session.to_dict()), session.dice.checkpoint()
        context = context_for(session, case["message"], case["confirmed"])
        accepted, reason = False, ""
        try:
            if case["confirmed"]:
                value = story_text(response(case["text"]), confirmed=True)
                check_story_quality(
                    value,
                    build_frame(session),
                    case["message"],
                    brief=context["turn_brief"],
                    campaign=context,
                )
            else:
                story_proposal(
                    response(case["text"]), build_frame(session), case["message"], context=context
                )
            accepted = True
        except (ValueError, TypeError, KeyError) as error:
            reason = type(error).__name__ + ": " + str(error)
        intact = (session.to_dict(), session.dice.checkpoint()) == before
        if not intact:
            raise RuntimeError("Validator mutated state or RNG: " + case["id"])
        results.append(
            {
                "id": case["id"],
                "valid": case["valid"],
                "accepted": accepted,
                "reason": reason,
                "state_and_rng_unchanged": intact,
            }
        )
    valid = [c for c in results if c["valid"]]
    invalid = [c for c in results if not c["valid"]]
    return {
        "kind": "authored synthetic replies; not actual DeepSeek inference",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "base_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_hashes": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "src/rpg_vkr/narrative").glob("*.py"))
        },
        "corpus_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "summary": {
            "valid_replies": len(valid),
            "valid_accepted": sum(c["accepted"] for c in valid),
            "valid_rejected": sum(not c["accepted"] for c in valid),
            "invalid_controls": len(invalid),
            "invalid_rejected": sum(not c["accepted"] for c in invalid),
            "invalid_accepted": sum(c["accepted"] for c in invalid),
            "actual_model_inferences": 0,
            "real_api_calls": 0,
        },
        "cases": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(value["summary"], ensure_ascii=False))
    return int(value["summary"]["valid_rejected"] > 0 or value["summary"]["invalid_accepted"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
