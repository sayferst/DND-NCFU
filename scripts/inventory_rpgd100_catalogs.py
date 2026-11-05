"""Exact site-wide catalog index, preserving source IDs without copying prose."""

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote

from import_rpgd100_facts import fetch

ROOT = Path(__file__).resolve().parents[1]


def main():
    html = fetch("https://rpgd100.ru/content_pages/catalog_index").decode("utf-8")
    paths = sorted(set(unquote(p) for p in re.findall(r'\?catalog=([^"&]+)', html)))

    def load(path):
        name = path.rsplit("/", 1)[-1]
        url = "https://rpgd100.ru/scripts/catalog_index/" + name + ".json"
        if "/materials/" in path or "/adventures/" in path:
            url = "https://rpgd100.ru/components/material_entries/" + name + ".links.json"
        try:
            raw = fetch(url)
            entries = json.loads(raw)
            if not isinstance(entries, list):
                raise ValueError("Expected array")
            return {
                "catalog": path,
                "index_url": url,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "entries": entries,
                "count": len(entries),
                "status": "ok",
            }
        except Exception as exc:
            return {"catalog": path, "index_url": url, "status": "error", "error": str(exc)}

    with ThreadPoolExecutor(max_workers=4) as pool:
        catalogs = list(pool.map(load, paths))
    output = {
        "format": "rpgd100-catalog-index-1",
        "catalogs": catalogs,
        "entries": sum(c.get("count", 0) for c in catalogs),
        "complete_indexes": all(c["status"] == "ok" for c in catalogs),
        "note": "Index metadata only; not a claim that all mechanics are implemented.",
    }
    path = ROOT / "data/world_library/rpgd100-all-indexes.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in output.items() if k != "catalogs"}))


if __name__ == "__main__":
    main()
