"""Inspect a supplied ZIP as data; no scripts, requests, game writes or auto-approval."""

import json
import re
import stat
from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import PurePosixPath
from zipfile import ZipFile

# These are format contracts, not assertions that synthetic mechanics are correct.
FORMATS = {
    "USER-SYN-0200": (r"^## ПАРТИЯ (\d{3,4})\.", 200, "session"),
    "USER-SYN-1000": (r"^## ПАРТИЯ (\d{3,4})\.", 1000, "session"),
    "USER-SYN-DEATH-1000": (r"^## Партия (\d{4})\.", 1000, "death_session"),
    "USER-SYN-EVENTS-1000": (r"^## ((?:EV|FI|LO|BA)-\d{3})\.", 1000, "event_template"),
    "USER-SYN-BEHAVIOR-5000": (r"^### #(\d{5}) · ([A-Z]+-\d+)\b", 5000, "behavior_template"),
    "USER-SYN-ENTITIES-5000": (r"^### #(\d{5}) · ([A-Z]+-\d+)\b", 5000, "world_template"),
    "USER-SYN-EVERYDAY-1000": (r"^### (\d{4})\.", 1000, "everyday_example"),
    "USER-SYN-CRAFT-5000": (r"^### #(\d{5}) · ([A-Z]+-\d+)\b", 5000, "crafting_definition"),
}
CATEGORIES = {
    "USER-SYN-EVENTS-1000": dict.fromkeys(["EV", "FI", "LO", "BA"], 250),
    "USER-SYN-BEHAVIOR-5000": dict(
        NPCM=950, MOBM=800, BOSSM=400, NSK=650, CSK=750, MAG=500, BOOK=500, SBOOK=450
    ),
    "USER-SYN-ENTITIES-5000": dict(
        MON=1000, WPN=650, ARM=450, GEAR=450, NPC=600, BOSS=300, PLANT=1000, PROF=350, KIN=200
    ),
    "USER-SYN-CRAFT-5000": dict(
        ORE=600,
        MAT=450,
        GEM=450,
        MCR=450,
        DROP=700,
        COMP=350,
        WPNC=400,
        EQPC=350,
        ENCH=400,
        POT=350,
        FOOD=500,
    ),
}
MAX_TOTAL = 128 * 1024 * 1024
SPEC = "DND_NCFU_CODEX_DEEPSEEK_DATA_TRAINING_MASTER_SPEC.md"
ALIAS = "DND_Training_Prompt.md"


@dataclass(frozen=True)
class LearningRecord:
    record_id: str
    record_type: str
    source_id: str
    source_path: str
    source_sha256: str
    start_line: int
    end_line: int
    title: str
    text_hash: str
    family_id: str
    category: str
    text: str
    canonical_id: str = ""
    rights_status: str = "local_only_provenance_unverified"
    quality_status: str = "unreviewed"
    ruleset_compatibility: str = "unchecked"
    approved_for_rag: bool = False
    approved_for_sft: bool = False
    third_party_transfer_allowed: bool = False
    usable_as_game_fact: bool = False


def normalize(text):
    return "\n".join(line.rstrip() for line in text.lstrip("\ufeff").splitlines()).strip()


def parse(raw, source_id, path):
    """Eight explicit heading grammars retain line spans and immutable raw SHA."""
    pattern, _, kind = FORMATS[source_id]
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    matches = list(re.finditer(pattern, text, re.M))
    lines = text.splitlines(keepends=True)
    offsets, offset = {}, 0
    for line_number, line in enumerate(lines, 1):
        offsets[offset] = line_number
        offset += len(line)
    digest = sha256(raw).hexdigest()
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = normalize(text[match.start() : end])
        local_id = match.group(2) if match.lastindex == 2 else match.group(1)
        if local_id.isdecimal():
            local_id = f"{int(local_id):04d}"
        category = local_id.split("-")[0] if "-" in local_id else kind
        # Known series stay together. Unknown families conservatively stay in
        # one source/category cluster; we do not invent independent holdout units.
        series = re.search(r"Сюжетная серия:\*\*\s*(\d+)/", block)
        family = f"series:{int(series[1])}" if series else category
        start_line = offsets[match.start()]
        end_line = offsets.get(end, len(lines) + 1) - 1
        yield LearningRecord(
            f"{source_id}:{local_id}",
            kind,
            source_id,
            path,
            digest,
            start_line,
            end_line,
            block.splitlines()[0],
            sha256(block.encode()).hexdigest(),
            f"{source_id}:{family}",
            category,
            block,
        )


def read_zip(path):
    """Bound compressed input; reject traversal/links/duplicates without extraction."""
    with ZipFile(path) as archive:
        rows = archive.infolist()
        if len(rows) > 100 or sum(r.file_size for r in rows) > MAX_TOTAL:
            raise ValueError("Пакет превышает предел100файлов/128МиБ.")
        result = {}
        for row in rows:
            name = PurePosixPath(row.filename)
            if (
                name.is_absolute()
                or ".." in name.parts
                or "\\" in row.filename
                or ":" in row.filename
                or stat.S_ISLNK(row.external_attr >> 16)
            ):
                raise ValueError("Недопустимый путь или ссылка внутри ZIP.")
            if row.is_dir():
                continue
            if row.filename in result or row.flag_bits & 1:
                raise ValueError("Повторяющийся или зашифрованный член ZIP.")
            result[row.filename] = archive.read(row)
        return result


def inspect(path, *, resolve_spec_alias=False):
    members = read_zip(path)
    manifest = json.loads(members["MANIFEST_Codex_Training_Sources.json"])
    errors, resolved, sources, records = [], [], [], []
    seen_sources = set()
    for row in manifest["sources"]:
        name, source = row["path"], row.get("source_id")
        data = members.get(name)
        if data is None and resolve_spec_alias and name == ALIAS:
            candidate = members.get(SPEC)
            if candidate is not None and sha256(candidate).hexdigest() == row["sha256"]:
                data = candidate
                resolved.append({"missing": ALIAS, "identical_source": SPEC, "virtual_only": True})
        if data is None:
            errors.append(f"Missing: {name}")
            continue
        digest = sha256(data).hexdigest()
        if digest != row["sha256"] or len(data) != row["bytes"]:
            errors.append(f"SHA/size mismatch: {name}")
        if source not in FORMATS:
            continue
        if source in seen_sources:
            errors.append(f"Duplicate source: {source}")
            continue
        seen_sources.add(source)
        try:
            parsed = list(parse(data, source, name))
        except UnicodeError:
            errors.append(f"Bad UTF-8: {name}")
            continue
        expected = FORMATS[source][1]
        ids = [r.record_id for r in parsed]
        cats = Counter(r.category for r in parsed)
        if len(parsed) != expected or len(set(ids)) != expected:
            errors.append(f"Count/IDs mismatch: {source}")
        if source in CATEGORIES and dict(cats) != CATEGORIES[source]:
            errors.append(f"Categories mismatch: {source}")
        pattern = FORMATS[source][0]
        headings = list(re.finditer(pattern, data.decode("utf-8-sig"), re.M))
        if source not in CATEGORIES or source.endswith("5000"):
            if [int(m[1]) for m in headings] != list(range(1, expected + 1)):
                errors.append(f"Sequence mismatch: {source}")
        if source in CATEGORIES:
            for cat, total in CATEGORIES[source].items():
                found = sorted(
                    int(r.record_id.rsplit("-", 1)[1]) for r in parsed if r.category == cat
                )
                if found != list(range(1, total + 1)):
                    errors.append(f"Category sequence mismatch: {source}/{cat}")
        long_lines = [
            line.strip()
            for line in data.decode("utf-8-sig").splitlines()
            if len(line.strip()) > 80 and not line.startswith("#")
        ]
        sources.append(
            {
                "source_id": source,
                "path": name,
                "sha256": digest,
                "records": len(parsed),
                "categories": dict(cats),
                "long_lines": len(long_lines),
                "repeated_long_lines": len(long_lines) - len(set(long_lines)),
                "rights": "local_only_provenance_unverified",
            }
        )
        records.extend(parsed)
    if seen_sources != set(FORMATS):
        errors.append("Missing corpus sources")
    main = {r.record_id.rsplit(":", 1)[1]: r for r in records if r.source_id == "USER-SYN-1000"}
    aliases = {}
    marker = "### Стенограмма партии"
    for record in records:
        if record.source_id != "USER-SYN-0200":
            continue
        candidate = main.get(record.record_id.rsplit(":", 1)[1])
        if (
            candidate
            and marker in record.text
            and marker in candidate.text
            and record.text.split(marker, 1)[1] == candidate.text.split(marker, 1)[1]
        ):
            aliases[record.record_id] = candidate.record_id
        else:
            errors.append(f"Legacy alias mismatch: {record.record_id}")
    unique = [r for r in records if r.record_id not in aliases]
    # Same full normalized text must stay in the same split regardless of source.
    # All records remain quarantined, so no test sample is indexed or tuned.
    counts = {
        "raw_structural_count": len(records),
        "parsed_count": len(records),
        "legacy_alias_count": len(aliases),
        "unique_canonical_count": len(unique),
        "quality_approved_count": 0,
        "indexed_count": 0,
        "heldout_count": 0,
        "sft_ready_count": 0,
    }
    report = {
        "format_version": 1,
        "archive_sha256": sha256(path.read_bytes()).hexdigest(),
        "verified": not errors,
        "original_package_complete": ALIAS in members,
        "errors": errors,
        "resolved_aliases": resolved,
        "sources": sources,
        "counts": counts,
        "aliases": aliases,
        "enabled": False,
        "raw_external_transfer": False,
        "artistic_quality": "not_assessed",
        "split_status": "quarantined_no_split",
        "rules_status": "unchecked_not_applied_to_game",
        "spec_sections": re.findall(r"^# (\d+)\. (.+)$", members[SPEC].decode(), re.M),
        "member_inventory": [
            {"path": name, "bytes": len(data), "sha256": sha256(data).hexdigest()}
            for name, data in sorted(members.items())
        ],
    }
    return report, unique


def write_records(path, records):
    """Explicit local export, no publication/approval; refuse to overwrite a prior run."""
    with path.open("x", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
