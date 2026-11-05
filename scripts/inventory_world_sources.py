"""Resumable site-wide link inventory; saves metadata, never republishes article bodies.

All same-host HTML paths are eligible. Budget is a runtime bound, not a selection
of entity types. External links, accounts, downloads and dynamic generators are
recorded as links but are not executed.
"""

import argparse
import hashlib
import json
import time
from collections import deque
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOTS = [
    "https://rpgd100.ru/",
    "https://dnd.su/",
    "https://ruleholder.com/",
    "https://longstoryshort.app/srd/",
]
HOSTS = {urlsplit(url).hostname for url in ROOTS}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()
        self.title = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag == "a":
            for key, value in attrs:
                if key == "href" and value:
                    self.links.add(value)

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)


def canonical(url):
    value = urlsplit(url)
    if value.scheme != "https" or value.hostname not in HOSTS or value.port not in (None, 443):
        return None
    if value.username or value.password or value.query:
        return None
    # Avoid binary assets, login routes, unbounded search and action endpoints.
    path = value.path or "/"
    if any(
        word in path.lower()
        for word in ("/login", "/logout", "/register", "/account", "/search", "/api/")
    ):
        return None
    if Path(path).suffix.lower() in {
        ".pdf",
        ".zip",
        ".jpg",
        ".png",
        ".svg",
        ".webp",
        ".mp4",
        ".exe",
    }:
        return None
    return urlunsplit(("https", value.hostname, path, "", ""))


def inventory(output, budget):
    previous = (
        json.loads(output.read_text(encoding="utf-8"))
        if output.exists()
        else {"pages": {}, "pending": ROOTS}
    )
    queue = deque(previous["pending"])
    pages = previous["pages"]
    attempts = 0
    while queue and attempts < budget:
        url = queue.popleft()
        if url in pages:
            continue
        attempts += 1
        result = {"url": url, "retrieved_at": datetime.now(UTC).isoformat()}
        try:
            request = Request(url, headers={"User-Agent": "DND-NCFU-Academic-Inventory/1.0"})
            with urlopen(request, timeout=15) as response:
                if canonical(response.url) is None:
                    raise ValueError("Redirect outside source scope")
                if "text/html" not in response.headers.get("Content-Type", ""):
                    raise ValueError("Not HTML")
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError("Page exceeds bound")
                parser = Links()
                parser.feed(
                    raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
                )
                links = sorted(
                    {
                        target
                        for link in parser.links
                        if (target := canonical(urljoin(response.url, link)))
                    }
                )
                result |= {
                    "status": "ok",
                    "title": " ".join(parser.title)[:200],
                    "html_sha256": hashlib.sha256(raw).hexdigest(),
                    "links": links,
                }
                for target in links:
                    if target not in pages and target not in queue:
                        queue.append(target)
        except (HTTPError, URLError, ValueError, TimeoutError, OSError) as exc:
            result |= {"status": "error", "error": str(exc)[:200]}
        pages[url] = result
        # Persist after each page; a later run continues the same inventory.
        state = {
            "format": "world-source-inventory-1",
            "pages": pages,
            "pending": list(queue),
            "complete": not queue,
            "policy": "metadata-only; no article bodies or inferred rights",
        }
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(output)
        time.sleep(0.4)
    print(json.dumps({"visited": len(pages), "pending": len(queue), "complete": not queue}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--pages", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.pages <= 10000:
        parser.error("pages must be 1..10000")
    inventory(args.output, args.pages)
