"""Typed factual parameters from source literals; no source code is executed."""

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from import_rpgd100_facts import fetch, literal_array  # noqa: E402

from rpg_vkr.world_library.model import dump, normalized, validate_bundle  # noqa: E402

ASSIGNMENT = re.compile(r"(?:(?:const|let|var)\s+|[,;]\s*)\w+\s*=\s*(?:Object\.freeze\(\s*)?[\[{]")
PRIMARY = {"classes", "races", "spells", "feats", "talents", "backgrounds", "magic_items_dnd5e"}


def catalog_records(value, name):
    if name not in PRIMARY:
        yield from named_records(value)
        return
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict):
            continue
        required = {
            "classes": {"id", "level_skills"},
            "races": {"name_ru", "characteristics"},
            "spells": {"name_ru", "level", "school"},
            "feats": {"name", "prerequisite"},
            "talents": {"name_ru", "group", "prerequisite"},
            "backgrounds": {"name_rus", "skills"},
            "magic_items_dnd5e": {"name_ru", "rarity", "attunement"},
        }[name]
        if required <= raw.keys():
            yield raw


def clean(value, maximum=200):
    value = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", str(value or ""), flags=re.S | re.I)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", value)).split())[:maximum]


class Visible(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1

    def handle_data(self, value):
        if not self.skip:
            self.parts.append(value)


def words(value):
    return " ".join(re.findall(r"\w+", clean(value, 100000).casefold()))


def resolve_by_card(attributes, choices):
    if len(choices) < 2:
        return choices
    url = (
        "https://rpgd100.ru/content_pages/catalog_index?catalog="
        + quote(attributes["source_catalog"], safe="")
        + "&entry="
        + quote(attributes["native_id"], safe="")
    )
    try:
        parser = Visible()
        parser.feed(fetch(url).decode("utf-8"))
        visible = words(" ".join(parser.parts))
    except (ValueError, OSError):
        return choices
    matches = []
    for raw, ancestor in choices:
        content = next(
            (
                raw[k]
                for k in (
                    "description",
                    "description_text",
                    "description_html",
                    "desc",
                    "content",
                    "html",
                )
                if isinstance(raw.get(k), str) and raw[k]
            ),
            "",
        )
        tokens = words(content).split()
        if len(tokens) < 12:
            continue
        positions = sorted({0, max(0, len(tokens) // 2 - 10), max(0, len(tokens) - 20)})
        if all(" ".join(tokens[pos : pos + 20]) in visible for pos in positions):
            matches.append((raw, ancestor))
    return matches if len(matches) == 1 else choices


def number(value, default=-1):
    if type(value) is int:
        return value
    match = re.search(r"\d+", clean(value))
    return int(match[0]) if match else default


def names(value):
    if isinstance(value, str):
        return [clean(value, 100)] if value else []
    if isinstance(value, list):
        return [clean(v, 100) for v in value if isinstance(v, str)][:50]
    return []


def dice(value):
    text = clean(value, 100000).replace("−", "-")
    return sorted(
        {
            re.sub(r"\s", "", m[0]).replace("к", "d")
            for m in re.finditer(
                r"\b[1-9][0-9]?\s*[кd](?:4|6|8|10|12|20|100)(?:\s*[+-]\s*\d+)?\b", text
            )
        }
    )[:100]


def slug(value):
    return re.sub(
        r"[^a-zа-яё0-9]+", "-", normalized(value).replace("'", "").replace("’", "")
    ).strip("-")


def source_bool(value):
    if type(value) is bool:
        return value
    text = clean(value).casefold()
    return text not in {"", "нет", "no", "false", "0", "—", "-"}


def source_book(raw):
    value = raw.get("source_book", raw.get("source", raw.get("source_eng", "")))
    return value.get("book", value.get("name", "")) if isinstance(value, dict) else str(value)


def source_name(row):
    return clean(
        row.get(
            "name_ru",
            row.get(
                "name_rus",
                row.get("name", row.get("название", row.get("title", row.get("tableName", "")))),
            ),
        )
    )


def name_keys(value):
    """Only explicit editorial prefixes/English glosses; no fuzzy identity merging."""
    value = re.sub(r"\s*\[.*\]$", "", value).strip()
    variants = {value, re.sub(r"\s*\([^)]*[A-Za-z][^)]*\)\s*$", "", value).strip()}
    tail = value
    while ": " in tail:
        tail = tail.split(": ", 1)[1]
        variants.add(tail)
    return {normalized(v) for v in variants if v}


def html_sections(page):
    """Keep section bodies transient; only original summaries/facts are exported."""
    headings = list(re.finditer(r"<h([1-6])\b[^>]*>(.*?)</h\1>", page, re.S | re.I))
    for i, heading in enumerate(headings):
        title = clean(heading[2]).strip(" #¶")
        end = headings[i + 1].start() if i + 1 < len(headings) else len(page)
        if title:
            yield {"title": title, "html": page[heading.end() : end]}


class CardSurface(HTMLParser):
    """Isolate the explicit entry surface, excluding menus and other cards."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if not self.depth:
            classes = dict(attrs).get("class", "").split()
            if tag != "div" or "catalog-index-entry-surface" not in classes:
                return
            self.depth = 1
            return
        self.parts.append(self.get_starttag_text())
        if tag == "div":
            self.depth += 1

    def handle_endtag(self, tag):
        if self.depth:
            if tag == "div":
                self.depth -= 1
            if self.depth:
                self.parts.append("</" + tag + ">")

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)

    def handle_entityref(self, name):
        if self.depth:
            self.parts.append("&" + name + ";")

    def handle_charref(self, name):
        if self.depth:
            self.parts.append("&#" + name + ";")


def source_card(attributes):
    url = (
        "https://rpgd100.ru/content_pages/catalog_index?catalog="
        + quote(attributes["source_catalog"], safe="")
        + "&entry="
        + quote(attributes["native_id"], safe="")
    )
    raw = fetch(url)
    parser = CardSurface()
    parser.feed(raw.decode("utf-8"))
    content = "".join(parser.parts)
    if not clean(content):
        raise ValueError("No source card surface")
    return {
        "title": attributes["source_name"],
        "html": content,
        "_asset": url,
        "_asset_sha256": hashlib.sha256(raw).hexdigest(),
    }


def table_calls(source):
    """Read literal arguments of table data constructors, without calling them."""
    for match in re.finditer(r'\b[A-Za-z_$]\w*\(\s*(?=["\'])', source):
        pos = source.find("(", match.start()) + 1
        start = pos
        depth, quote_char, escaped = 1, "", False
        while pos < len(source) and pos - start < 1000000:
            char = source[pos]
            if quote_char:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote_char:
                    quote_char = ""
            elif char in {'"', "'", chr(96)}:
                quote_char = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if not depth:
                    break
            pos += 1
        if depth:
            continue
        try:
            args = literal_array(
                "const args=[" + source[start:pos] + "]", allow_duplicate_keys=True
            )
        except (ValueError, IndexError):
            continue
        if (
            len(args) == 3
            and isinstance(args[0], str)
            and isinstance(args[1], str)
            and isinstance(args[2], list)
        ):
            yield {
                "tableName": args[0],
                "description": args[1],
                "dimension": "к" + str(len(args[2])),
                "items": [{"id": str(i + 1), "text": value} for i, value in enumerate(args[2])],
            }


def named_records(value, inherited=None):
    inherited = inherited or {}
    if isinstance(value, dict):
        fields = inherited | {
            k: value[k] for k in ("source", "source_book", "rarity", "type") if k in value
        }
        if source_name(value) and set(value) & {
            "description",
            "description_text",
            "description_html",
            "desc",
            "описание",
            "content",
            "html",
            "rows",
            "entries",
            "items",
            "статблок",
            "effects",
            "level_skills",
            "cost",
            "points",
        }:
            yield inherited | value
            content = value.get("content", value.get("html"))
            if isinstance(content, str):
                headings = list(
                    re.finditer(
                        r"<(?:h[1-6]|summary)[^>]*>(.*?)</(?:h[1-6]|summary)>", content, re.S | re.I
                    )
                )
                for i, heading in enumerate(headings):
                    title = clean(heading[1]).strip(" #¶")
                    if title:
                        stop = headings[i + 1].start() if i + 1 < len(headings) else len(content)
                        yield fields | {"title": title, "content": content[heading.end() : stop]}
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from named_records(child, fields)
    elif isinstance(value, list):
        for child in value:
            yield from named_records(child, inherited)


class Progression(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cell = None
        self.cells = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells = []
        if tag in {"td", "th"}:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.cells.append(clean(" ".join(self.cell)))
            self.cell = None
        if tag == "tr" and len(self.cells) >= 2:
            level = number(self.cells[0])
            if 1 <= level <= 20 and re.fullmatch(r"\+?[2-6]", self.cells[1]):
                self.rows.append({"level": level, "proficiency": number(self.cells[1])})


def load_catalog(name, page_path=None):
    page_url = "https://rpgd100.ru" + (page_path or "/content_pages/" + name)
    page_raw = fetch(page_url)
    page = page_raw.decode("utf-8")
    matches = re.findall(r'<script[^>]+src="([^"]+)"', page)
    assets = [value for value in matches if value.split("/")[-1].split("?", 1)[0].startswith(name)]
    if name == "tables":
        assets += [value for value in matches if "/scripts/table_" in value]
    if not assets:
        assets = ["/scripts/" + name + ".js"]
    records = []
    if name not in PRIMARY:
        records.extend(
            v | {"_asset": page_url, "_asset_sha256": hashlib.sha256(page_raw).hexdigest()}
            for v in html_sections(page)
        )
    for asset in dict.fromkeys(assets):
        url = "https://rpgd100.ru" + unescape(asset)
        raw = fetch(url)
        source = raw.decode("utf-8")
        for assignment in ASSIGNMENT.finditer(source):
            try:
                value = literal_array(source[assignment.start() :], allow_duplicate_keys=True)
            except (ValueError, IndexError):
                continue
            records.extend(
                v | {"_asset": url, "_asset_sha256": hashlib.sha256(raw).hexdigest()}
                for v in catalog_records(value, name)
            )
        if name == "tables":
            records.extend(
                v | {"_asset": url, "_asset_sha256": hashlib.sha256(raw).hexdigest()}
                for v in table_calls(source)
            )
    for attributes, body in re.findall(r"<script([^>]*)>(.*?)</script>", page, re.S | re.I):
        if not re.search(r'type=["\']application/json["\']', attributes, re.I):
            continue
        if name != "conditions" and re.search(r'\bid=["\'][^"\']*conditions', attributes, re.I):
            continue
        try:
            extra = json.loads(body)
        except ValueError:
            continue
        if isinstance(extra, (list, dict)):
            identity = re.search(r'id=["\']([^"\']+)', attributes)
            origin = page_url + ("#" + identity[1] if identity else "")
            records.extend(
                v | {"_asset": origin, "_asset_sha256": hashlib.sha256(page_raw).hexdigest()}
                for v in catalog_records(extra, name)
            )

            # Some readers publish section JSON URLs in a bootstrap object.
            # Follow only first-party data assets, never executable bootstrap code.
            def section_urls(value):
                if isinstance(value, dict):
                    url = value.get("dataUrl", "")
                    if isinstance(url, str) and re.fullmatch(
                        r"/scripts/[\w/.-]+\.json(?:\?[\w=&.-]+)?", url
                    ):
                        yield url
                    for child in value.values():
                        yield from section_urls(child)
                elif isinstance(value, list):
                    for child in value:
                        yield from section_urls(child)

            for section_url in dict.fromkeys(section_urls(extra)):
                url = "https://rpgd100.ru" + section_url
                section_raw = fetch(url)
                content = json.loads(section_raw)
                records.extend(
                    v | {"_asset": url, "_asset_sha256": hashlib.sha256(section_raw).hexdigest()}
                    for v in catalog_records(content, name)
                )
    unique = {}
    for row in records:
        key = dump({k: v for k, v in row.items() if not k.startswith("_asset")})
        unique.setdefault(key, row)
    return list(unique.values()), page_url, hashlib.sha256(page_raw).hexdigest()


def feature_details(raw, parent, parent_id, children, level=None):
    table = Progression()
    table.feed(parent.get("general_table", "") if raw is parent else "")
    hit = re.search(r"[кd](4|6|8|10|12)", str(parent.get("hit_dice", "")))
    return {
        "source_class_id": parent["id"],
        "parent_global_id": parent_id,
        "minimum_level": number(raw.get("level")) if level is None else level,
        "hit_die_sides": int(hit[1]) if hit else -1,
        "progression": table.rows[:20],
        "child_ids": children,
        "source_dice": dice(raw.get("description", "")),
        "source_fields": [
            k for k in ("id", "level", "hit_dice", "general_table", "source_book") if k in raw
        ],
    }


def scalar_time(value):
    text = clean(value).casefold()
    if "бонус" in text:
        return "bonus_action", 1
    if "реакц" in text:
        return "reaction", 1
    if "действ" in text:
        return "action", number(text, 1)
    for word, unit in (
        ("раунд", "round"),
        ("минут", "minute"),
        ("час", "hour"),
        ("день", "day"),
        ("дней", "day"),
    ):
        if word in text:
            return unit, number(text, 1)
    if "мгнов" in text:
        return "instant", 0
    return "special", -1


def spell_details(raw):
    casting, amount = scalar_time(raw.get("application_time", ""))
    duration, duration_amount = scalar_time(raw.get("duration", ""))
    multiplier = {"instant": 0, "round": 6, "minute": 60, "hour": 3600, "day": 86400}
    distance = clean(raw.get("distance", "")).casefold()
    kind = (
        "feet"
        if "фут" in distance
        else "self"
        if "на себя" in distance
        else "touch"
        if "касание" in distance
        else "special"
    )
    components = clean(raw.get("components", "")).casefold()
    seconds = (
        duration_amount * multiplier[duration]
        if duration in multiplier and duration_amount >= 0
        else -1
    )
    return {
        "level": number(raw.get("level")),
        "school": clean(raw.get("school", ""), 100),
        "casting_unit": casting,
        "casting_amount": amount,
        "range_kind": kind,
        "range_feet": number(distance) if kind == "feet" else -1,
        "duration_kind": duration,
        "duration_seconds": seconds,
        "components": [
            name
            for tokens, name in (
                (r"\b[вv]\b", "verbal"),
                (r"\b[сs]\b", "somatic"),
                (r"\b[мm]\b", "material"),
            )
            if re.search(tokens, components)
        ],
        "class_names": names(raw.get("classes", [])),
        "ritual": source_bool(raw.get("ritual", False)),
        "concentration": source_bool(raw.get("concentration", False)),
        "source_dice": dice(raw.get("description", "")),
        "source_fields": [
            k
            for k in (
                "level",
                "school",
                "application_time",
                "distance",
                "duration",
                "components",
                "classes",
                "ritual",
                "concentration",
            )
            if k in raw
        ],
    }


def race_details(raw, parent_id, children):
    bonuses = []
    for bonus in raw.get("characteristics", []):
        if isinstance(bonus, dict):
            bonuses.extend(
                {"ability": str(k), "bonus": v}
                for k, v in bonus.items()
                if type(v) is int and -10 <= v <= 10
            )
    return {
        "creature_type": clean(raw.get("type", ""), 100),
        "sizes": names(raw.get("size", []))[:5],
        "speed_walk_ft": number(raw.get("speed_land")),
        "speed_fly_ft": number(raw.get("speed_air")),
        "speed_swim_ft": number(raw.get("speed_water")),
        "speed_climb_ft": number(raw.get("speed_climb")),
        "darkvision_ft": number(raw.get("dark_vision")),
        "languages": names(raw.get("languages", [])),
        "skill_names": names(raw.get("skills", [])),
        "ability_bonuses": bonuses[:20],
        "parent_global_id": parent_id,
        "child_ids": children,
        "source_dice": dice(raw.get("description_text", raw.get("description", ""))),
        "source_fields": [
            k
            for k in (
                "type",
                "size",
                "speed_land",
                "speed_air",
                "speed_water",
                "speed_climb",
                "dark_vision",
                "languages",
                "skills",
                "characteristics",
            )
            if k in raw
        ],
    }


def trait_details(raw):
    prerequisite = clean(raw.get("prerequisite", ""))
    requirements = [
        {"ability": ability, "minimum": int(match[1])}
        for word, ability in (
            ("сил", "strength"),
            ("ловк", "dexterity"),
            ("телослож", "constitution"),
            ("интеллект", "intelligence"),
            ("мудр", "wisdom"),
            ("харизм", "charisma"),
        )
        if (match := re.search(word + r"[а-яё]*\s+(\d+)", prerequisite, re.I))
        and 1 <= int(match[1]) <= 40
    ]
    level = re.search(r"(?:уровень\s*(\d+)|(\d+)[-–]?[а-я]*\s+уров)", prerequisite, re.I)
    structured = raw.get("prerequisite") if isinstance(raw.get("prerequisite"), dict) else {}
    if structured:
        requirements = [
            {"ability": str(value["name"]), "minimum": value["value"]}
            for value in structured.get("ability", [])
            if isinstance(value, dict)
            and type(value.get("value")) is int
            and 1 <= value["value"] <= 40
        ]
    effects = raw.get("effects") if isinstance(raw.get("effects"), dict) else {}
    prof = effects.get("proficiencies", {})
    spells = effects.get("spellcasting", {})
    combat = effects.get("combat_effects", {})
    increases = [
        {
            "ability": str(value.get("ability", "")),
            "amount": value["value"],
            "maximum": value.get("maximum", -1),
        }
        for value in effects.get("ability_score_increase", [])
        if isinstance(value, dict) and type(value.get("value")) is int
    ]
    return {
        "minimum_level": number(structured.get("level"))
        if structured
        else int(level[1] or level[2])
        if level
        else -1,
        "prerequisite_mode": "complex" if prerequisite else "none",
        "ability_requirements": requirements,
        "required_classes": names(structured.get("classes", [])),
        "required_races": names(structured.get("races", [])),
        "required_skills": names(structured.get("skills", [])),
        "required_spells": names(structured.get("spells", [])),
        "required_feats": names(structured.get("feats", [])),
        "other_prerequisite_present": bool(structured.get("other")),
        "ability_increases": increases,
        "armour_class_bonus": combat.get("armor_class_bonus", 0) or 0,
        "spellcasting_ability": clean(spells.get("ability"), 100),
        "granted_spells": names(spells.get("spells", [])),
        "granted_skills": names(prof.get("skills", {}).get("granted", [])),
        "granted_tools": names(prof.get("tools", [])),
        "granted_weapons": names(prof.get("weapons", [])),
        "granted_armour": names(prof.get("armor", [])),
        "custom_rule_count": len(effects.get("custom_effects", [])),
        "tags": names(raw.get("tags", [])),
        "source_dice": dice(raw.get("description", "")),
        "source_fields": [k for k in ("prerequisite", "tags", "effects", "group") if k in raw],
    }


def other_details(raw, role="section"):
    numbers, booleans = [], []

    def visit(value, prefix="", depth=0):
        if depth > 3 or len(numbers) >= 100 or len(booleans) >= 100:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if key.startswith("_") or key in {
                    "description",
                    "content",
                    "text",
                    "description_text",
                    "описание",
                    "author_link",
                    "translator_link",
                }:
                    continue
                field = (prefix + "." + key).strip(".")[:120]
                if type(child) is bool:
                    booleans.append({"field": field, "value": child})
                elif type(child) is int and -(10**9) <= child <= 10**9:
                    numbers.append({"field": field, "value": child})
                elif isinstance(child, dict):
                    visit(child, field, depth + 1)

    visit(raw)
    content = next(
        (
            raw[k]
            for k in ("html", "content", "description_html", "desc")
            if isinstance(raw.get(k), str)
        ),
        "",
    )
    # Read numeric table cells and labelled facts only, never turn prose into rules.
    for table_row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", content, re.S | re.I):
        cells = [
            clean(c, 150)
            for c in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", table_row, re.S | re.I)
        ]
        if len(cells) < 2 or not 1 <= len(cells[0]) <= 70:
            continue
        for col, cell in enumerate(cells[1:], 1):
            if re.fullmatch(r"[+−-]?\d{1,9}(?:\s*(?:фт\.?|футов|кг|зм|см|мм|м|%))?", cell):
                number_match = re.search(r"[+-]?\d+", cell.replace("−", "-"))
                numbers.append(
                    {"field": (cells[0] + f" [column {col}]")[:120], "value": int(number_match[0])}
                )
    outcomes = raw.get("items", raw.get("rows", raw.get("entries", [])))
    return {
        "source_fields": [k for k in raw if not k.startswith("_")][:100],
        "source_dice": dice(content or raw.get("description", "")),
        "node_role": role,
        "numeric_parameters": numbers[:100],
        "boolean_parameters": booleans[:100],
        "outcome_count": len(outcomes) if isinstance(outcomes, list) else -1,
        "die_sides": number(raw.get("dimension", raw.get("dice", ""))),
    }


def magic_details(raw):
    content = raw.get("description", raw.get("description_html", raw.get("content", "")))
    charges = number(raw.get("charges"))
    if charges == -1:
        match = re.search(r"(?:имеет|содержит)\s+(\d+)\s+заряд", clean(content, 100000), re.I)
        charges = int(match[1]) if match else -1
    return {
        "rarity": clean(
            raw.get("rarity", raw.get("rarity_ru", raw.get("type_and_rarity", ""))), 100
        ),
        "item_type": clean(raw.get("type", raw.get("type_ru")), 150),
        "subtype": clean(raw.get("subtype", raw.get("second_type", "")), 150),
        "requires_attunement": source_bool(raw.get("attunement")),
        "charges_max": charges,
        "source_price": clean(raw.get("price"), 150),
        "source_dice": dice(content),
        "source_fields": [
            k
            for k in (
                "rarity",
                "type",
                "type_and_rarity",
                "subtype",
                "second_type",
                "attunement",
                "charges",
                "price",
            )
            if k in raw
        ],
    }


def main():
    directory = ROOT / "data/world_library"
    path = directory / "rpgd100-reference-index.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    catalogs = {
        name: load_catalog(name)
        for name in (
            "classes",
            "races",
            "spells",
            "feats",
            "talents",
            "backgrounds",
            "magic_items_dnd5e",
        )
    }
    load_errors = []
    for source_path in sorted({row["attributes"]["source_catalog"] for row in rows}):
        name = source_path.rsplit("/", 1)[-1]
        if name in catalogs:
            continue
        try:
            catalogs[name] = load_catalog(name, source_path)
        except (ValueError, OSError) as exc:
            load_errors.append({"source": source_path, "error": str(exc)[:200]})
    classes = {r["id"]: r for r in catalogs["classes"][0] if "id" in r and "level_skills" in r}
    root_ids, skill_ids = {}, {}
    subclass_ids = defaultdict(list)
    for row in rows:
        a = row["attributes"]
        if a["source_catalog"] != "/content_pages/classes":
            continue
        url = urlsplit(a["source_url"])
        query = parse_qs(url.query)
        if query.get("skill"):
            skill_ids[query["skill"][0]] = row["id"]
        elif query.get("class"):
            if not url.fragment:
                root_ids[query["class"][0]] = row["id"]
            else:
                subclass_ids[query["class"][0]].append(row)
    candidates = {}
    for catalog, (source_rows, _, _) in catalogs.items():
        index = defaultdict(list)
        for raw_index, raw in enumerate(source_rows):
            if catalog == "races":
                raw["_race_key"] = raw_index
            aliases = name_keys(source_name(raw))
            english = raw.get("name_en", raw.get("name_eng", ""))
            if isinstance(english, str) and english:
                aliases |= name_keys(english)
                aliases |= name_keys(source_name(raw).replace(english, "").strip(" ()"))
            for key in aliases:
                index[key].append((raw, ""))
            if catalog == "races":
                for child in raw.get("subraces", []):
                    if isinstance(child, dict):
                        merged = raw | child
                        merged.pop("subraces", None)
                        index[normalized(re.sub(r"\s*\[.*\]$", "", source_name(child)))].append(
                            (merged, source_name(raw))
                        )
        candidates[catalog] = index
    matched = Counter()
    matched_races = []
    for row in rows:
        a = row["attributes"]
        catalog = a["source_catalog"].rsplit("/", 1)[-1]
        if catalog not in catalogs:
            a.update(
                record_type="other",
                details=other_details({}, "unresolved"),
                source_asset=a["source_url"],
                source_asset_sha256="",
                data_state="needs-source-resolution",
            )
            continue
        _, asset, sha = catalogs[catalog]
        raw = None
        record_type = "other"
        details = other_details({}, "unresolved")
        if a["section"].startswith("Фильтр"):
            a.update(
                record_type="other",
                details=other_details({"index": True}, "control"),
                source_asset=a["source_url"],
                source_asset_sha256="",
                data_state="index-control",
            )
            matched["index-controls"] += 1
            continue
        query = parse_qs(urlsplit(a["source_url"]).query)
        if catalog == "classes":
            token = query.get("skill", [""])[0].split(":")
            class_id = token[0] if len(token) > 1 else query.get("class", [""])[0]
            parent = classes.get(class_id)
            if parent:
                children = []
                parent_global = root_ids.get(class_id, "")
                if len(token) == 3 and token[1] == "base":
                    raw = parent["level_skills"][int(token[2])]
                elif len(token) == 4 and token[1] == "subclass":
                    subindex, feature_index = int(token[2]), int(token[3])
                    raw = parent["subclasses"][subindex]["skills"][feature_index]
                elif not urlsplit(a["source_url"]).fragment:
                    raw, parent_global = parent, ""
                    children = [
                        skill_ids[class_id + ":base:" + str(i)]
                        for i in range(len(parent["level_skills"]))
                        if class_id + ":base:" + str(i) in skill_ids
                    ]
                    children += [r["id"] for r in subclass_ids[class_id]]
                else:
                    title = a["source_name"].split(":", 1)[-1].strip()
                    options = [
                        sub
                        for sub in parent["subclasses"]
                        if normalized(re.sub(r"\s*[\[(].*$", "", clean(sub["name"])))
                        == normalized(title)
                    ]
                    if len(options) > 1:
                        fragment = unquote(urlsplit(a["source_url"]).fragment)
                        specific = [
                            sub
                            for sub in options
                            if slug(source_book(sub)) and slug(source_book(sub)) in fragment
                        ]
                        if len(specific) == 1:
                            options = specific
                    if len(options) > 1:
                        options = [
                            raw for raw, _ in resolve_by_card(a, [(raw, "") for raw in options])
                        ]
                    if len(options) == 1:
                        raw = options[0]
                        subindex = parent["subclasses"].index(raw)
                        children = [
                            skill_ids[f"{class_id}:subclass:{subindex}:{i}"]
                            for i in range(len(raw["skills"]))
                            if f"{class_id}:subclass:{subindex}:{i}" in skill_ids
                        ]
                if raw:
                    record_type = "class"
                    details = feature_details(
                        raw, parent, parent_global, children, 1 if raw is parent else None
                    )
        else:
            name = re.sub(r"\s*\[.*\]$", "", a["source_name"]).strip()
            choices = []
            aliases = name_keys(name) | name_keys(a["english_name"])
            gloss = re.search(r"\[([^\]]+)\]$", a["source_name"])
            if gloss:
                aliases |= name_keys(gloss[1])
            for key in sorted(aliases):
                for option in candidates[catalog].get(key, []):
                    if option not in choices:
                        choices.append(option)
            if catalog == "races" and not choices and ": " in name:
                ancestor_name, leaf = name.rsplit(": ", 1)
                choices = [
                    (raw, ancestor)
                    for raw, ancestor in candidates[catalog].get(normalized(leaf), [])
                    if normalized(ancestor) == normalized(ancestor_name)
                ]
            if len(choices) > 1:
                fragment = unquote(
                    urlsplit(a["source_url"]).fragment or urlsplit(a["source_url"]).query
                )
                if catalog == "backgrounds":
                    specific = [
                        (raw, ancestor)
                        for raw, ancestor in choices
                        if fragment.endswith("-" + slug(raw.get("source_abbr", "")))
                    ]
                    if len(specific) == 1:
                        choices = specific
                if catalog == "talents":
                    specific = [
                        (raw, ancestor)
                        for raw, ancestor in choices
                        if any(
                            roman in raw.get("source", "") and code in fragment
                            for roman, code in (
                                ("Talents IV", "-t4"),
                                ("Talents III", "-t3"),
                                ("Talents II", "-t2"),
                                ("Talents I ", "-t1"),
                            )
                        )
                    ]
                    if specific:
                        choices = specific
                ranked = [
                    (
                        len(slug(source_book(raw))) if slug(source_book(raw)) in fragment else 0,
                        raw,
                        ancestor,
                    )
                    for raw, ancestor in choices
                ]
                best = max(score for score, _, _ in ranked)
                choices = [(raw, ancestor) for score, raw, ancestor in ranked if score == best]
            choices = resolve_by_card(a, choices)
            if len(choices) > 1 and catalog in {"feats", "talents"}:
                signatures = {dump(trait_details(raw)) for raw, _ in choices}
                if len(signatures) == 1:
                    choices = choices[
                        :1
                    ]  # Only equal extracted parameters; identities remain separate.
            if len(choices) == 1:
                raw, _ = choices[0]
                if catalog == "spells":
                    record_type, details = "spell", spell_details(raw)
                elif catalog == "races":
                    record_type, details = "race", race_details(raw, "", [])
                    matched_races.append((row, raw, choices[0][1]))
                elif catalog in {"feats", "talents"}:
                    record_type, details = "trait", trait_details(raw)
                elif catalog == "magic_items_dnd5e":
                    record_type = "magic_item"
                    details = magic_details(raw)
                elif catalog == "backgrounds":
                    record_type = "background"
                    details = {
                        "skill_names": names(raw.get("skills", [])),
                        "tool_names": names(raw.get("tools", [])),
                        "language_names": names(raw.get("languages", [])),
                        "source_dice": dice(raw.get("description", "")),
                        "source_fields": [k for k in ("skills", "tools", "languages") if k in raw],
                    }
                elif {"rarity", "rarity_ru", "type_and_rarity"} & raw.keys():
                    record_type, details = "magic_item", magic_details(raw)
                else:
                    record_type, details = (
                        "other",
                        other_details(raw, "table" if catalog == "tables" else "source-section"),
                    )
        if raw:
            asset = raw.get("_asset", asset)
            sha = raw.get("_asset_sha256", sha)
        a.update(
            record_type=record_type,
            details=details,
            source_asset=asset,
            source_asset_sha256=sha,
            data_state="source-structured" if raw else "needs-source-resolution",
        )
        if raw:
            matched[catalog] += 1
            summary = [
                f"{key}: {value}"
                for key, value in details.items()
                if key not in {"source_fields", "child_ids", "source_dice", "progression"}
                and value not in ("", -1, [], False)
            ]
            row["description"] = (
                f"{a['source_name'][:200]}. "
                + "; ".join(summary)
                + ". Параметры извлечены из источника; "
                "они не заменяют проверку правил применения движком."
            )[:1700]
    pending = [
        row
        for row in rows
        if row["attributes"]["data_state"] == "needs-source-resolution"
        and not row["attributes"]["source_catalog"].endswith(("/classes", "/races"))
    ]
    card_errors = []

    def resolve_card(row):
        try:
            return row, source_card(row["attributes"]), None
        except (ValueError, OSError) as exc:
            return row, None, str(exc)[:160]

    # Two requests in flight; cached bodies remain outside the released dataset.
    with ThreadPoolExecutor(max_workers=2) as pool:
        for index, (row, raw, error) in enumerate(pool.map(resolve_card, pending), 1):
            a = row["attributes"]
            if error:
                card_errors.append({"id": row["id"], "error": error})
                continue
            a.update(
                record_type="other",
                details=other_details(raw, "source-section"),
                source_asset=raw["_asset"],
                source_asset_sha256=raw["_asset_sha256"],
                data_state="source-section",
            )
            row["description"] = (
                f"{a['source_name'][:200]} — раздел исходного сборника. "
                "Его существование и доступная числовая разметка проверены по "
                "отдельной карточке. Полные условия правил не переведены в "
                "исполняемую модель; отсутствующие параметры неизвестны."
            )
            matched[a["source_catalog"].rsplit("/", 1)[-1]] += 1
            if index % 50 == 0:
                print(dump({"source_cards_checked": index, "of": len(pending)}), flush=True)
    for row in rows:
        a = row["attributes"]
        d = a.get("details", {})
        if a.get("record_type") == "other" and a["data_state"] == "source-structured":
            if not (
                d["numeric_parameters"]
                or d["boolean_parameters"]
                or d["source_dice"]
                or d["outcome_count"] >= 0
            ):
                a["data_state"] = "source-section"
    by_id = {row["id"]: row for row in rows}
    for row, raw, ancestor in matched_races:
        if ancestor:
            parents = [
                parent
                for parent, data, leaf in matched_races
                if not leaf and data["_race_key"] == raw["_race_key"]
            ]
            if len(parents) == 1:
                parent = parents[0]
                row["attributes"]["details"]["parent_global_id"] = parent["id"]
                parent["attributes"]["details"]["child_ids"].append(row["id"])
    # The child list is authoritative, including subclass -> subclass feature.
    for row in rows:
        a = row["attributes"]
        if a.get("record_type") not in {"class", "race"}:
            continue
        for child in a["details"]["child_ids"]:
            by_id[child]["attributes"]["details"]["parent_global_id"] = row["id"]
    for row in rows:
        a = row["attributes"]
        if a.get("record_type") not in {"class", "race"}:
            continue
        detail = a["details"]
        row["links"] = [
            {"relation": "child", "target": target, "quantity": 1, "role": "source hierarchy"}
            for target in detail["child_ids"]
        ]
        if detail["parent_global_id"]:
            row["links"].append(
                {
                    "relation": "parent",
                    "target": detail["parent_global_id"],
                    "quantity": 1,
                    "role": "source hierarchy",
                }
            )
    from rpg_vkr.world_library.model import read_jsonl, validate_record

    for row in rows:
        try:
            validate_record(row)
        except ValueError as exc:
            raise ValueError(row["attributes"]["source_name"] + ": " + str(exc)) from exc
    base = []
    for name in ("seed-v1.jsonl", "rpgd100-creature-facts.jsonl", "rpgd100-equipment-facts.jsonl"):
        base.extend(read_jsonl(directory / name))
    validate_bundle(base + rows)
    path.write_text("\n".join(dump(row) for row in rows) + "\n", encoding="utf-8")
    report = {
        "matched_by_catalog": dict(matched),
        "enriched": sum(matched.values()),
        "reference_records": len(rows),
        "unresolved": len(rows) - sum(matched.values()),
        "parser": "literal-data; JavaScript duplicate keys use last value; no eval",
        "full_mechanical_implementation": False,
        "source_load_errors": load_errors,
        "source_card_errors": card_errors,
        "data_states": dict(Counter(row["attributes"]["data_state"] for row in rows)),
        "record_types": dict(Counter(row["attributes"]["record_type"] for row in rows)),
    }
    (directory / "reference-enrichment.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(dump(report))


if __name__ == "__main__":
    main()
