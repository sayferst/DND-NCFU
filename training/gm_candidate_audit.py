"""Audit every native source candidate without declaring source prose to be gold data."""

import argparse
import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from training.fireball_observations import dumps
from training.gm_mechanics import MECHANICS, hp_observation, prose_evidence
from training.select_gm_curriculum import context_contains
from training.source_gm_curation import OOC, source_messages, text_screen
from training.tokenize_dataset import FAUN_TEMPLATE_SHA, PinnedFaunTokenizer

VERSION = "gm-native-candidate-audit-1"
CHATTER = re.compile(
    r"\b(?:lol|lmao|idk|imo|irl|brb|rofl|discord|chat room|"
    r"subscribe|sponsor|next thursday|next episode)\b|:pepe\w*:|~~|(?m:^\s*//)",
    re.I,
)
DEATH = re.compile(
    r"\b(?:dies|is dead|falls dead|killed|slain|decapitat\w*|"
    r"finish(?:es|ed)?\s+(?:him|her|it|them)\s+off)\b",
    re.I,
)


def native_messages(case):
    if case["source"] == "PROJECT_REFERENCE":
        return case["context"]["messages"]
    return source_messages(case["context"]["task"], case["context"])


def quality_flags(case):
    """Conservative diagnostics, not an automated semantic/human approval."""
    if case["source"] == "PROJECT_REFERENCE":
        return []
    context, target = case["context"], case["target"]
    flags = []
    reason = text_screen(target, grounded=context["task"] == "narrate_confirmed_outcome")
    if reason:
        flags.append(reason)
    if OOC.search(dumps(context)):
        flags.append("INPUT_CONTAINS_PRODUCTION_OR_OUT_OF_GAME_DISCUSSION")
    if CHATTER.search(target):
        flags.append("CHATTER_OR_MARKUP_REQUIRES_EDITORIAL_REVIEW")
    if DEATH.search(target):
        flags.append("DEATH_NOT_ESTABLISHED_BY_AVAILABLE_SOURCE_RECEIPT")
    if context_contains(context, target):
        flags.append("EXACT_TARGET_IN_INPUT")
    if context.get("task") == "continue_dm_scene" and not context.get("history"):
        flags.append("SCENE_HAS_NO_PRECEDING_DIALOGUE")
    if re.search(r"\byou (?:decide|choose|agree|want)\b", target, re.I):
        flags.append("PLAYER_AGENCY_REQUIRES_CONTEXT_REVIEW")
    actors = context.get("actors", {})
    before = {a["name"]: a for a in actors.get("before", []) if isinstance(a.get("name"), str)}
    after = {a["name"]: a for a in actors.get("after", []) if isinstance(a.get("name"), str)}
    results = "\n".join(context.get("confirmed_result", {}).get("automation_results", []))
    if context["task"] == "narrate_confirmed_outcome" and re.search(
        r"\b(?:multiple matches found|no matches found|could not find|unknown attack|"
        r"invalid target|error|not enough spell slots)\b",
        results,
        re.I,
    ):
        flags.append("AUTOMATION_ERROR_IS_NOT_A_CONFIRMED_OUTCOME")
    # A discrepancy may be missing resistance/temporary HP or stale/backfilled source data.
    # Retain it for reconciliation; never repair a recorded HP value by guessing.
    for name in before.keys() & after.keys():
        old, new = hp_observation(before[name].get("hp")), hp_observation(after[name].get("hp"))
        damage = re.findall(re.escape(name) + r" took (\d+) damage\.", results)
        if old and new and damage and "temp" not in before[name].get("hp", ""):
            if old[1] != new[1] or max(0, old[0] - sum(map(int, damage))) != new[0]:
                flags.append("SOURCE_STATE_AND_AUTOMATION_NEED_RECONCILIATION")
                break
    return flags


def fingerprint(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def audit(cases, output, tokenizer_path, *, independent=False):
    cases, output = Path(cases), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    config = {
        "model_family": "faun_mistral_nemo",
        "chat_template_sha256": FAUN_TEMPLATE_SHA,
        "max_length": 2**31,
    }
    tokenizer = PinnedFaunTokenizer(tokenizer_path, config)
    auto = None
    if independent:
        from transformers import AutoTokenizer

        auto = AutoTokenizer.from_pretrained(
            tokenizer_path, local_files_only=True, trust_remote_code=False
        )
    groups, units, prompt_folds, target_folds, ids = (
        {},
        set(),
        defaultdict(set),
        defaultdict(set),
        set(),
    )
    flags, sources, folds, lengths = Counter(), Counter(), Counter(), Counter()
    domains = {
        name: {"source_context": Counter(), "target_mentions": Counter()} for name in MECHANICS
    }
    total_tokens, assistant_tokens, human, maximum = 0, 0, 0, 0
    with (
        gzip.open(cases, "rt", encoding="utf-8") as stream,
        gzip.open(output / "audit-ledger.jsonl.gz", "wt", encoding="utf-8") as dest,
    ):
        for number, line in enumerate(stream, 1):
            case = json.loads(line)
            key, fold, group = case["id"], case["split"], case["group_id"]
            if key in ids or groups.setdefault(group, fold) != fold:
                raise ValueError("Duplicate candidate or source group crosses splits")
            ids.add(key)
            units.add((case["source"], case["source_unit"]))
            sources[case["source"]] += 1
            folds[fold] += 1
            human += case.get("human_reviewed") is True
            messages = native_messages(case)
            prompt_folds[fingerprint(messages)].add(fold)
            target_folds[fingerprint(case["target"])].add(fold)
            answer = case["target"]
            control = any(
                t in dumps(messages) + answer for t in ("<|im_start|>", "<|im_end|>", "<s>", "</s>")
            )
            if control:
                raise ValueError("Source candidate contains a chat control token")
            prefix = tokenizer.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=True, return_dict=False
            )
            full = tokenizer.apply_chat_template(
                messages + [{"role": "assistant", "content": answer}],
                tokenize=True,
                add_generation_prompt=False,
            )
            if full[: len(prefix)] != prefix:
                raise ValueError("Native source ChatML prefix differs")
            if auto is not None and (
                list(
                    auto.apply_chat_template(
                        messages, tokenize=True, add_generation_prompt=True, return_dict=False
                    )
                )
                != prefix
                or list(
                    auto.apply_chat_template(
                        messages + [{"role": "assistant", "content": answer}],
                        tokenize=True,
                        add_generation_prompt=False,
                        return_dict=False,
                    )
                )
                != full
            ):
                raise ValueError("Independent AutoTokenizer disagrees with pinned encoder")
            total, supervised = len(full), len(full) - len(prefix)
            if supervised < 3 or full[-2:] != [131072, 1010]:
                raise ValueError("Empty supervised source target or wrong ChatML ending")
            profile = next((str(n) for n in (2048, 4096, 8192) if total <= n), "OVER_8192_RETAINED")
            lengths[profile] += 1
            total_tokens += total
            assistant_tokens += supervised
            maximum = max(maximum, total)
            reasons = quality_flags(case)
            flags.update(reasons)
            for domain, evidence in case["mechanics_evidence"].items():
                domains[domain]["source_context"][case["source"] + ":" + evidence] += 1
            for domain, evidence in prose_evidence(answer).items():
                domains[domain]["target_mentions"][case["source"] + ":" + evidence] += 1
            dest.write(
                dumps(
                    {
                        "id": key,
                        "source": case["source"],
                        "split": fold,
                        "group_id": group,
                        "prompt_tokens": len(prefix),
                        "assistant_tokens": supervised,
                        "total_tokens": total,
                        "minimum_length_profile": profile,
                        "review_reasons": reasons,
                        "human_reviewed": False,
                        "train_admitted": False,
                    }
                )
                + "\n"
            )
            if number % 5000 == 0:
                print(
                    dumps({"native_candidates_audited": number, "tokens": total_tokens}), flush=True
                )
    report = {
        "schema": VERSION,
        "status": "NATIVE_CANDIDATES_AUDITED_NOT_ADMITTED",
        "source_cases_sha256": file_digest(cases),
        "rows": len(ids),
        "unique_source_units": len(units),
        "source_counts": dict(sources),
        "splits": dict(folds),
        "groups": len(groups),
        "group_cross_split": 0,
        "prompt_hashes_cross_split": sum(len(v) > 1 for v in prompt_folds.values()),
        "target_hashes_cross_split": sum(len(v) > 1 for v in target_folds.values()),
        "minimum_length_profiles": dict(lengths),
        "total_tokens": total_tokens,
        "assistant_tokens": assistant_tokens,
        "max_total": maximum,
        "review_flags": dict(flags),
        "mechanics": domains,
        "human_approved": human,
        "train_admitted": 0,
        "training_steps": 0,
        "model_weights_loaded": False,
        "independent_auto_tokenizer_samples": len(ids) if auto is not None else 0,
        "semantic_limit": "COUNTS_AND_TOKENIZATION_ARE_NOT_MEANING_OR_RULE_COMPATIBILITY_APPROVAL",
        "source_limit": (
            "DM_ACCOUNT_AND_TRANSCRIBER_ROLE_ARE_NOT_PROOF_EVERY_LINE_IS_A_GOOD_MASTER_REPLY"
        ),
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cases", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--tokenizer", type=Path, required=True)
    p.add_argument("--independent", action="store_true")
    a = p.parse_args()
    report = audit(a.cases, a.output, a.tokenizer, independent=a.independent)
    print(json.dumps({k: report[k] for k in ("status", "rows", "train_admitted")}))


if __name__ == "__main__":
    main()
