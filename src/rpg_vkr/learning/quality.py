"""Deterministic corpus diagnostics, role boundaries and conservative grouped splits.

Machine annotations are candidates for review, never human approval or game truth.
"""

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass

VERSION = "corpus-qc-1"
NAMESPACES = {
    "session": "narrative",
    "death_session": "consequences",
    "event_template": "events",
    "behavior_template": "behavior",
    "world_template": "entities",
    "everyday_example": "adjudication",
    "crafting_definition": "crafting",
}
UNSAFE = re.compile(
    r"ignore (?:all |previous )?instructions|system prompt|api[_ -]?key\s*[:=]|"
    r"игнорируй (?:все |предыдущие )?инструкции|выведи (?:ключ|токен)|"
    r"(?:sk-|sk_)[a-zA-Z0-9_-]{16,}",
    re.I,
)
PRIVATE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}|\+\d[\d ()-]{9,}", re.I)
CLAIM = re.compile(
    r"\b(?:HP|MP|AC|DC|XP|СЛ|КЗ)\s*[=:]?\s*\d+|\b\d+d\d+(?:[+-]\d+)?|"
    r"\b\d+\s*(?:мед\.|золот\w*|серебр\w*|MP|HP)",
    re.I,
)
ROLE = re.compile(
    r"^\s*(?:\*\*)?(?:Ход\s*(\d+)\s*[—–-]\s*)?"
    r"(Игрок[^:*\n]*|Квитанция движка|Результат игрового движка|Мастер[^:*\n]*)"
    r"\s*(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.*)$",
    re.I,
)
REF = re.compile(
    r"\b(?:NPCM|MOBM|BOSSM|MON|NPC|BOSS|PLANT|MAT|ORE|GEM|MCR|DROP|COMP|"
    r"WPNC|EQPC|ENCH|POT|FOOD|CSK|NSK|MAG|BOOK|SBOOK)-\d{3,5}\b"
)


@dataclass(frozen=True)
class RoleLine:
    role: str
    sequence: int
    text: str
    annotation_source: str = "explicit_label"


def roles(text):
    """Retain independent ordered statements; absent receipts stay absent."""
    result = []
    for line in text.splitlines():
        match = ROLE.match(line)
        if not match:
            continue
        label, body = match[2].casefold(), match[3].strip()
        role = (
            "player"
            if label.startswith("игрок")
            else ("narrator" if label.startswith("мастер") else "engine_example")
        )
        result.append(RoleLine(role, len(result) + 1, body))
    return tuple(result)


def fields(text):
    """Extract labelled candidate fields without interpreting prose as state changes."""
    values = defaultdict(list)
    for key, value in re.findall(r"\*\*([^*:\n]{1,90}):\*\*\s*([^\n]*)", text):
        values[key.strip()].append(value.strip())
    return dict(values)


def safe_excerpt(text):
    return not (UNSAFE.search(text) or PRIVATE.search(text)) and not any(
        ord(c) < 32 and c not in "\n\t" for c in text
    )


def signature(text):
    # Numeric variants of one template must not become independent eval samples.
    body = "\n".join(text.splitlines()[1:]).casefold().replace("ё", "е")
    body = REF.sub(" reference ", body.upper()).casefold()
    body = re.sub(r"\b\d+(?:[.,]\d+)?\b", " number ", body)
    return " ".join(re.findall(r"[a-zа-яё_]+", body))


def sketch(value):
    tokens = value.split()[:900]
    grams = {" ".join(tokens[i : i + 4]) for i in range(max(0, len(tokens) - 3))}
    return frozenset(
        sorted(
            int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "big")
            for g in grams
        )[:96]
    )


def family(record):
    series = re.search(r"Сюжетная серия:\*\*\s*(\d+)/", record.text)
    if series:
        return f"story-series:{int(series[1])}"
    if record.record_type == "event_template":
        number = int(record.record_id.rsplit("-", 1)[1])
        return f"{record.source_id}:{record.category}:base:{(number - 1) // 10}"
    if record.record_type == "everyday_example":
        number = int(record.record_id.rsplit(":", 1)[1])
        return f"{record.source_id}:sphere:{(number - 1) // 20}"
    title = re.sub(
        r"^#+\s*(?:#\d+\s*·\s*[A-Z]+-\d+|Партия\s+\d+\.)\s*[—-]?\s*", "", record.title, flags=re.I
    )
    base = title.split(" — ", 1)[0].split(":", 1)[0].split(",", 1)[0].strip()
    if base and base != record.title:
        digest = hashlib.sha256(base.casefold().encode()).hexdigest()[:20]
        return f"{record.source_id}:{record.category}:base:{digest}"
    return record.family_id


def annotate(record):
    reasons = []
    claims = tuple(dict.fromkeys(m.group() for m in CLAIM.finditer(record.text)))[:50]
    if not safe_excerpt(record.text):
        reasons.append("unsafe_instruction_or_personal_data")
    if claims:
        reasons.append("mechanics_require_engine_mapping")
    if re.search(
        r"\b(?:герой|вы)\s+(?:обязан|обязаны|неизбежно соглаш|автоматически получ)",
        record.text,
        re.I,
    ):
        reasons.append("possible_forced_agency_or_reward")
    ordered = roles(record.text)
    if record.record_type in {"session", "death_session"} and not ordered:
        reasons.append("unrecognized_turn_roles")
    lines = [line.strip() for line in record.text.splitlines() if len(line.strip()) > 80]
    if lines and len(set(lines)) < len(lines):
        reasons.append("repeated_long_line_in_record")
    status = (
        "rejected"
        if "unsafe_instruction_or_personal_data" in reasons
        else ("needs_review" if reasons else "machine_validated")
    )
    return {
        "record_id": record.record_id,
        "namespace": NAMESPACES[record.record_type],
        "template_or_instance": "example"
        if record.record_type in {"session", "death_session"}
        else "template",
        "quality_status": status,
        "annotation_source": "heuristic",
        "artistic_quality": "not_assessed",
        "mechanics_compatible": False,
        "mechanics_claims": claims,
        "reasons": reasons,
        "fields": fields(record.text),
        "roles": [asdict(v) for v in ordered],
        "references": sorted(set(REF.findall(record.text))),
        "family_id": family(record),
    }


def grouped(records, *, cancelled=lambda: False, progress=lambda value: None):
    """Bounded LSH candidates plus exact/family unions, never independent-row splits.

    Conservative source/category groups survive when no narrower family is known.
    LSH is a diagnostic with bounded candidates, not a semantic-uniqueness proof.
    """
    parent = {r.record_id: r.record_id for r in records}

    def root(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(a, b):
        left, right = sorted((root(a), root(b)))
        parent[right] = left

    families, hashes, buckets, sketches = {}, {}, defaultdict(list), {}
    exact, near, comparisons = 0, 0, 0
    for index, record in enumerate(records):
        if cancelled():
            raise InterruptedError("Импорт отменён; действующий индекс сохранён.")
        key = record.record_id
        group = family(record)
        if group in families:
            union(key, families[group])
        else:
            families[group] = key
        normalized = signature(record.text)
        digest = hashlib.sha256(normalized.encode()).hexdigest()
        if digest in hashes:
            union(key, hashes[digest])
            exact += 1
        else:
            hashes[digest] = key
        current = sketch(normalized)
        candidates = set()
        for token in sorted(current)[:4]:
            candidates.update(buckets[token][-24:])
        for other in sorted(candidates)[:96]:
            if root(key) == root(other):
                continue
            previous = sketches[other]
            comparisons += 1
            similarity = len(current & previous) / max(1, len(current | previous))
            if similarity >= 0.88:
                union(key, other)
                near += 1
        sketches[key] = current
        for token in sorted(current)[:4]:
            buckets[token].append(key)
        if index % 100 == 0:
            progress(index)
    groups = {r.record_id: root(r.record_id) for r in records}
    splits = {}
    for key, group in groups.items():
        bucket = int(hashlib.sha256((VERSION + group).encode()).hexdigest()[:8], 16) % 100
        splits[key] = "train" if bucket < 80 else "dev" if bucket < 90 else "test"
    return (
        groups,
        splits,
        {
            "groups": len(set(groups.values())),
            "normalized_exact_links": exact,
            "near_duplicate_links": near,
            "candidate_comparisons": comparisons,
            "split_counts": dict(Counter(splits.values())),
            "split_group_overlap": 0,
            "semantic_independence": "not_proven",
            "near_duplicate_threshold": 0.88,
        },
    )
