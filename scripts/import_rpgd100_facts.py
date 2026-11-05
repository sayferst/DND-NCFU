"""Import factual stat fields without executing JS or copying narrative/action prose."""

import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rpg_vkr.world_library.model import dump, schemas, validate_bundle  # noqa: E402


def literal_array(source):
    """Restricted data grammar: objects/arrays/JSON scalars and minified booleans."""
    match = re.search(r"(?:const|let|var)\s+\w+\s*=\s*\[", source)
    if not match:
        raise ValueError("No literal array")
    pos = match.end() - 1
    decoder = json.JSONDecoder()

    def string():
        nonlocal pos
        quote = source[pos]
        pos += 1
        result = []
        escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v"}
        while pos < len(source):
            char = source[pos]
            pos += 1
            if char == quote:
                return "".join(result)
            if char == "\\":
                char = source[pos]
                pos += 1
                if char in {"u", "x"}:
                    count = 4 if char == "u" else 2
                    result.append(chr(int(source[pos : pos + count], 16)))
                    pos += count
                else:
                    result.append(escapes.get(char, char))
            else:
                result.append(char)
        raise ValueError("Unterminated string")

    def read():
        nonlocal pos
        while source[pos].isspace():
            pos += 1
        char = source[pos]
        if char in {'"', "'"}:
            return string()
        if char in "[{":
            pos += 1
            value = [] if char == "[" else {}
            end = "]" if char == "[" else "}"
            while True:
                while source[pos].isspace():
                    pos += 1
                if source[pos] == end:
                    pos += 1
                    return value
                if char == "{":
                    if source[pos] in {'"', "'"}:
                        key = string()
                    else:
                        token = re.compile(r"[A-Za-z_$][\w$]*").match(source, pos)
                        if not token:
                            raise ValueError("Invalid key")
                        key = token[0]
                        pos += len(key)
                    while source[pos].isspace():
                        pos += 1
                    if source[pos] != ":":
                        raise ValueError("Expected colon")
                    pos += 1
                    if key in value:
                        raise ValueError("Duplicate key")
                    value[key] = read()
                else:
                    value.append(read())
                while source[pos].isspace():
                    pos += 1
                if source[pos] == ",":
                    pos += 1
                elif source[pos] != end:
                    raise ValueError("Nonliteral data")
        if source.startswith(("!0", "!1"), pos):
            result = source[pos + 1] == "0"
            pos += 2
            return result
        result, pos = decoder.raw_decode(source, pos)
        return result

    return read()


def fetch(url):
    cache = ROOT.parent / "rpg-source-cache"
    cache.mkdir(exist_ok=True)
    path = cache / hashlib.sha256(url.encode()).hexdigest()
    if path.exists():
        return path.read_bytes()
    with urlopen(url, timeout=30) as response:
        raw = response.read(30_000_001)
        if len(raw) > 30_000_000:
            raise ValueError("Source too large")
        path.write_bytes(raw)
        return raw


def extend_schema(spec):
    from build_world_library import array, number, obj, text

    profiles = spec["record"]["properties"]["profile"]["enum"]
    if "source_creature" not in profiles:
        profiles.append("source_creature")
    origins = spec["record"]["properties"]["provenance"]["properties"]["origin"]["enum"]
    if "source-facts/original-description" not in origins:
        origins.append("source-facts/original-description")
    spec["source_creature"] = obj(
        {
            "source_url": text(600),
            "source_catalog": text(100),
            "source_name": text(160),
            "source_type": text(100, 0),
            "source_size": text(100, 0),
            "hp": number(0, 1000000),
            "challenge_rating": text(40, 0),
            "speed": text(200, 0),
            "alignment": text(100, 0),
            "armour_class": number(0, 100),
            "abilities": obj(
                {key: number(0, 40) for key in ("str", "dex", "con", "int", "wis", "cha")}
            ),
            "missing_fields": array(text(), 20),
            "feature_names": array(text(200), 80),
            "appearance_homebrew": text(800),
            "mechanics": text(300),
        }
    )
    spec["source_creature"]["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    if "source_equipment" not in profiles:
        profiles.append("source_equipment")
    spec["source_equipment"] = obj(
        {
            "source_url": text(600),
            "source_name": text(160),
            "section": text(100, 0),
            "facts": array(obj({"field": text(40), "value": text(180, 0)}), 30),
            "missing_numeric_facts": {"type": "boolean"},
            "price_status": text(200),
        }
    )
    spec["source_equipment"]["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return spec


def run():
    out = ROOT / "data/world_library"
    spec = extend_schema(json.loads((out / "schemas.json").read_text(encoding="utf-8")))
    (out / "schemas.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    schemas.cache_clear()
    url = "https://rpgd100.ru/content_pages/materials/all_bestiaries"
    html = fetch(url).decode("utf-8")
    paths = set(re.findall(r'href="(/content_pages/[^"?#]+)', html))
    paths.add("/content_pages/bestiary_dnd5e")
    sources = []
    records = []
    errors = []
    seen = set()
    for path in sorted(paths):
        if any(x in path for x in ("privacy", "equipment", "spells")):
            continue
        page_url = urljoin(url, path)
        try:
            page = fetch(page_url).decode("utf-8")
            scripts = re.findall(r'<script[^>]+src="([^"?]+)', page)
            for script in scripts:
                if not any(
                    k in script
                    for k in (
                        "bestiary",
                        "grimoire",
                        "monsters",
                        "creatures",
                        "beasts",
                        "dinosaurs",
                        "drakkenheim",
                        "tome",
                        "familiars",
                        "horrors",
                        "dogs",
                        "encounters",
                        "arcadia",
                        "horses",
                        "tasha",
                        "steinhardt",
                    )
                ):
                    continue
                script_url = urljoin(page_url, script)
                if script_url in seen:
                    continue
                seen.add(script_url)
                raw = fetch(script_url)
                try:
                    source = raw.decode("utf-8")
                    data = []
                    for assignment in re.finditer(r"(?:const|let|var)\s+\w+\s*=\s*\[", source):
                        try:
                            data.extend(literal_array(source[assignment.start() :]))
                        except (ValueError, IndexError):
                            continue
                except ValueError as exc:
                    if "No literal array" in str(exc):
                        continue
                    raise
                found = 0
                for entry in data:
                    if not isinstance(entry, dict) or "статблок" not in entry:
                        continue
                    stat = entry["статблок"]
                    name = entry.get("название", entry.get("id", ""))
                    if not name:
                        continue
                    missing = []
                    abilities = {}
                    for key, source_key in zip(
                        ("str", "dex", "con", "int", "wis", "cha"),
                        ("сил", "лов", "тел", "инт", "муд", "хар"),
                        strict=True,
                    ):
                        value = stat.get("характеристики", {}).get(source_key)
                        abilities[key] = value if type(value) is int and 0 <= value <= 40 else 0
                        if not abilities[key]:
                            missing.append(key)

                    def numeric(key, stat=stat, missing=missing):
                        value = stat.get(key)
                        if type(value) is int:
                            return value
                        match = re.match(r"\d+", str(value))
                        if match:
                            return int(match[0])
                        missing.append(key)
                        return 0

                    hp = numeric("хиты")
                    ac = numeric("класс_доспеха")
                    kind = stat.get("тип", "")
                    size = stat.get("размер", "")
                    if not isinstance(kind, str):
                        kind = ""
                    if not isinstance(size, str):
                        size = ""
                    slug = entry.get("slug", entry.get("id", name))
                    source_url = page_url + "?monster=" + str(slug)
                    id = (
                        "rpg_"
                        + hashlib.sha256((script_url + "#" + str(slug)).encode()).hexdigest()[:24]
                    )
                    features = []
                    for group in (
                        "черты",
                        "действия",
                        "легендарные_действия",
                        "мифические_действия",
                        "реакции",
                    ):
                        values = stat.get(group, [])
                        if isinstance(values, list):
                            for value in values:
                                if isinstance(value, dict) and isinstance(
                                    value.get("название"), str
                                ):
                                    features.append(
                                        " ".join(re.sub(r"<[^>]+>", "", value["название"]).split())[
                                            :200
                                        ]
                                    )
                    from rpg_vkr.world_library.appearance import appearance as visual_variant

                    appearance = visual_variant(id, name, kind, size)
                    row = {
                        "id": id,
                        "name": (name[:65] + " · " + id[-8:]),
                        "profile": "source_creature",
                        "category": "reference.source_creature",
                        "price_cp": 0,
                        "description": (
                            f"Справочная запись «{name}». Тип: {kind or 'не указан'}; "
                            f"размер: {size or 'не указан'}. Числовые параметры извлечены "
                            f"из источника. Текст биографии и описания действий не "
                            f"перенесён; игровые эффекты не подключены автоматически."
                        ),
                        "attributes": {
                            "source_url": source_url,
                            "source_catalog": path.split("/")[-1],
                            "source_name": name[:160],
                            "source_type": kind[:100],
                            "source_size": size[:100],
                            "hp": hp,
                            "challenge_rating": str(
                                stat.get("опасность", {}).get("показатель", "")
                            )[:40],
                            "speed": str(stat.get("скорость", ""))[:200],
                            "alignment": str(stat.get("мировоззрение", ""))[:100],
                            "armour_class": ac,
                            "abilities": abilities,
                            "missing_fields": missing,
                            "feature_names": features[:80],
                            "appearance_homebrew": appearance,
                            "mechanics": (
                                "reference-only; engine handler required; zero means "
                                "unavailable, not an assigned statistic"
                            ),
                        },
                        "links": [],
                        "provenance": {
                            "origin": "source-facts/original-description",
                            "source": source_url[:400],
                            "generator": "rpg-facts-1",
                            "review": "unreviewed",
                        },
                    }
                    records.append(row)
                    found += 1
                if found:
                    sources.append(
                        {
                            "url": script_url,
                            "records": found,
                            "sha256": hashlib.sha256(raw).hexdigest(),
                        }
                    )
        except Exception as exc:
            errors.append({"url": page_url, "error": str(exc)[:200]})
    unique = {r["id"]: r for r in records}
    records = list(unique.values())
    base = [
        json.loads(line)
        for line in (out / "seed-v1.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if len(base) + len(records) > 20000:
        raise ValueError("Total library would exceed 20000; curate before import")
    validate_bundle(base + records)
    (out / "rpgd100-creature-facts.jsonl").write_text(
        "\n".join(dump(r) for r in records) + "\n", encoding="utf-8"
    )
    report = {
        "retrieved_at": datetime.now(UTC).isoformat(),
        "records": len(records),
        "total_with_original_seed": len(base) + len(records),
        "limit": 20000,
        "sources": sources,
        "errors": errors,
        "by_catalog": dict(Counter(r["attributes"]["source_catalog"] for r in records)),
        "complete_all_bestiaries": False,
        "note": (
            "Only discovered literal stat arrays; no copied "
            "narrative/action descriptions. Missing values flagged, not "
            "guessed."
        ),
    }
    (out / "rpgd100-import-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(dump(report))


if __name__ == "__main__":
    run()
