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


def literal_array(source, *, allow_duplicate_keys=False):
    """Restricted data grammar: objects/arrays/JSON scalars and minified booleans."""
    match = re.search(
        r"(?:(?:const|let|var)\s+|[,;]\s*)\w+\s*=\s*(?:Object\.freeze\(\s*)?[\[{]", source
    )
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
                    if key in value and not allow_duplicate_keys:
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
        if char in "+-.0123456789":
            token = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?").match(source, pos)
            if token:
                pos = token.end()
                number = token[0]
                return float(number) if any(c in number for c in ".eE") else int(number)
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


def literal_bindings(source):
    """Read comma-separated declarations too; this never evaluates JavaScript."""
    pattern = r"(?:(?:const|let|var)\s+|[,;]\s*)\w+\s*=\s*(?:Object\.freeze\(\s*)?[\[{]"
    for match in re.finditer(pattern, source):
        try:
            value = literal_array(source[match.start() :], allow_duplicate_keys=True)
        except (ValueError, IndexError):
            continue
        yield value


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
            "resistances": array(text(30), 14),
            "immunities": array(text(30), 14),
            "vulnerabilities": array(text(30), 14),
            "regeneration": number(0, 100),
            "extra_attacks": number(0, 2),
            "attacks": array(
                obj(
                    {
                        "name": text(200),
                        "bonus": number(-10, 40),
                        "dice": text(40),
                        "element": text(30),
                        "partial": {"type": "boolean"},
                    }
                ),
                30,
            ),
            "appearance_homebrew": text(800),
            "mechanics": text(300),
        }
    )
    spec["source_creature"]["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    spec["source_creature"]["properties"]["attack_math_version"] = {
        "type": "integer",
        "enum": [2],
    }
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
    spec["source_equipment"]["properties"].update(
        source_asset=text(1000),
        source_asset_sha256={"type": "string", "pattern": "[0-9a-f]{64}"},
        purpose_homebrew=text(300),
        appearance_homebrew=text(600),
        history_homebrew=text(300),
        design_origin={"type": "string", "enum": ["invented/homebrew"]},
    )
    if "source_reference" not in profiles:
        profiles.append("source_reference")
    spec["source_reference"] = obj(
        {
            "source_url": text(1000),
            "source_name": text(250),
            "source_catalog": text(200),
            "native_id": text(160),
            "english_name": text(200, 0),
            "section": text(150, 0),
            "mechanics_state": {"type": "string", "enum": ["reference-only"]},
        }
    )
    spec["source_reference"]["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    from rpg_vkr.world_library.reference_details import register

    register(spec)
    from rpg_vkr.world_library.creature_actions import register as register_actions

    register_actions(spec)
    from rpg_vkr.world_library.magic_rules import register as register_magic

    register_magic(spec)
    from rpg_vkr.world_library.source_extract import register as register_source

    register_source(spec)
    from rpg_vkr.world_library.resilience_rules import register as register_resilience

    register_resilience(spec)
    from rpg_vkr.world_library.equipment_packs import register as register_packs

    register_packs(spec)
    from rpg_vkr.world_library.regeneration_rules import register as register_regeneration

    register_regeneration(spec)
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
                    attacks = []
                    regeneration = 0
                    extra_attacks = 0
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
                                    prose = re.sub(r"<[^>]+>", " ", value.get("описание", ""))
                                    lower = prose.casefold()
                                    if "регенерац" in value["название"].casefold() and not any(
                                        word in lower
                                        for word in (
                                            "если",
                                            "пока",
                                            "кроме",
                                            "огн",
                                            "кислот",
                                            "солнеч",
                                            "свят",
                                            "излучен",
                                        )
                                    ):
                                        healing = re.search(r"восстанавливает\s+(\d+)\s+хит", lower)
                                        if healing and "начале" in lower and "хода" in lower:
                                            regeneration = min(100, int(healing[1]))
                                    bonus_match = re.search(
                                        r"([+-]\s*\d+)\s*к\s*попаданию", prose, re.I
                                    )
                                    dice_match = re.search(
                                        r"\b([1-9][0-9]?)\s*[кd](4|6|8|10|12)(\s*[+-]\s*[0-9]{1,2})?",
                                        prose,
                                    )
                                    if bonus_match and dice_match and len(attacks) < 30:
                                        bonus = int(bonus_match[1].replace(" ", ""))
                                        if -10 <= bonus <= 40:
                                            dice = (
                                                dice_match[1]
                                                + "d"
                                                + dice_match[2]
                                                + (dice_match[3] or "").replace(" ", "")
                                            )
                                            attacks.append(
                                                {
                                                    "name": features[-1],
                                                    "bonus": bonus,
                                                    "dice": dice,
                                                    "element": next(
                                                        (
                                                            element
                                                            for word, element in (
                                                                ("огн", "fire"),
                                                                ("холод", "cold"),
                                                                ("электр", "lightning"),
                                                                ("кислот", "acid"),
                                                                ("некрот", "necrotic"),
                                                                ("излуч", "radiant"),
                                                                ("псих", "psychic"),
                                                                ("ядом", "poison"),
                                                                ("звуком", "thunder"),
                                                            )
                                                            if word
                                                            in prose[
                                                                dice_match.end() : dice_match.end()
                                                                + 60
                                                            ].casefold()
                                                        ),
                                                        "physical",
                                                    ),
                                                    "partial": any(
                                                        word in lower
                                                        for word in (
                                                            "спасброс",
                                                            "если",
                                                            "отравлен",
                                                            "схвачен",
                                                            "опутан",
                                                            "очарован",
                                                            "испуган",
                                                            "сбит",
                                                            "парализован",
                                                        )
                                                    ),
                                                }
                                            )
                    if len(attacks) == 1:
                        for action in stat.get("действия", []):
                            if (
                                isinstance(action, dict)
                                and str(action.get("название") or "").casefold() == "мультиатака"
                            ):
                                prose = str(action.get("описание") or "").casefold()
                                if not any(
                                    word in prose for word in ("или", "если", "заклин", "может")
                                ):
                                    if re.search(r"совершает\s+две\s+атаки", prose):
                                        extra_attacks = 1
                                    elif re.search(r"совершает\s+три\s+атаки", prose):
                                        extra_attacks = 2

                    def elements(field, stat=stat):
                        value = stat.get(field, [])
                        if isinstance(value, dict):
                            value = value.get("урон", [])
                        if isinstance(value, str):
                            value = re.split(r"[,;]", value)
                        if not isinstance(value, list):
                            return []
                        known = {
                            "огонь": "fire",
                            "огню": "fire",
                            "огнём": "fire",
                            "холод": "cold",
                            "холоду": "cold",
                            "холодом": "cold",
                            "электричество": "lightning",
                            "электричеству": "lightning",
                            "электричеством": "lightning",
                            "кислота": "acid",
                            "кислоте": "acid",
                            "кислотой": "acid",
                            "яд": "poison",
                            "яду": "poison",
                            "ядом": "poison",
                            "некротическая энергия": "necrotic",
                            "излучение": "radiant",
                            "психическая энергия": "psychic",
                            "звук": "thunder",
                        }
                        return sorted(
                            {
                                known[s.strip().casefold()]
                                for s in value
                                if isinstance(s, str) and s.strip().casefold() in known
                            }
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
                            "resistances": elements("сопротивления"),
                            "immunities": elements("иммунитеты"),
                            "vulnerabilities": elements("уязвимости"),
                            "regeneration": regeneration,
                            "extra_attacks": extra_attacks,
                            "attacks": attacks,
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
    if sum(r["attributes"]["source_catalog"] == "bestiary_dnd5e" for r in records) != 2874:
        raise ValueError("Primary bestiary coverage regressed; refusing to replace complete seed")
    base = [
        json.loads(line)
        for line in (out / "seed-v1.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if len(base) + len(records) > 100000:
        raise ValueError("Library exceeds resource safety bound")
    validate_bundle(base + records)
    (out / "rpgd100-creature-facts.jsonl").write_text(
        "\n".join(dump(r) for r in records) + "\n", encoding="utf-8"
    )
    report = {
        "retrieved_at": datetime.now(UTC).isoformat(),
        "records": len(records),
        "total_with_original_seed": len(base) + len(records),
        "limit": 100000,
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
