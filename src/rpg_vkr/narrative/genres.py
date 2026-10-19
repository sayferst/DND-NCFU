"""Small original craft cards; no scraping, literary corpus or paid search service."""

import json
import re
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def cards():
    path = Path(__file__).resolve().parents[3] / "data/narrative/genre-cards-v1.json"
    return tuple(json.loads(path.read_text(encoding="utf-8"))["cards"])


def relevant_cards(brief):
    text = brief.casefold()
    scored = []
    for card in cards():
        matched = [tag for tag in card["tags"] if tag in text]
        if any(
            re.search(r"(?:без|никак\w*|no)\s+(?:\w+\s+){0,2}" + re.escape(tag), text)
            for tag in matched
        ):
            continue
        if matched:
            scored.append((len(matched), card))
    selected = [card for _, card in sorted(scored, key=lambda pair: -pair[0])[:2]]
    return [
        {"id": c["id"], "pattern": c["pattern"], "references": c["links"]}
        for c in (selected or cards()[:1])
    ]
