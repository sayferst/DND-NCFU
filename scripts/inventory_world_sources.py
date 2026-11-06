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
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOTS = [
    "https://rpgd100.ru/",
    "https://dnd.su/",
    "https://ruleholder.com/",
    "https://longstoryshort.app/srd/",
    "https://longstoryshort.app/",
    "https://next.dnd.su/",
]
HOSTS = {urlsplit(url).hostname for url in ROOTS}


def replace_checkpoint(temporary, output):
    """Windows readers/antivirus may briefly deny an otherwise atomic replacement."""
    for attempt in range(10):
        try:
            temporary.replace(output)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(min(0.05 * (attempt + 1), 0.5))


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
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        return None
    value = urlsplit(url)
    if value.scheme not in {"http", "https"} or value.hostname not in HOSTS:
        return None
    if value.port not in (None, 80 if value.scheme == "http" else 443):
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
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        return None
    path = quote(path, safe="/%:@!$&'()*+,;=-._~")
    return urlunsplit(("https", value.hostname, path, "", ""))


class SourceRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = canonical(newurl)
        if target is None:
            raise ValueError("Redirect outside source scope")
        return super().redirect_request(req, fp, code, msg, headers, target)


def read_page(url, cache_dir, throttle):
    result = {"url": url, "retrieved_at": datetime.now(UTC).isoformat()}
    try:
        address = canonical(url)
        if address is None:
            raise ValueError("URL outside source scope")
        throttle(urlsplit(address).hostname)
        request = Request(address, headers={"User-Agent": "DND-NCFU-Academic-Inventory/1.0"})
        with build_opener(SourceRedirects()).open(request, timeout=15) as response:
            if canonical(response.url) is None:
                raise ValueError("Redirect outside source scope")
            if "text/html" not in response.headers.get("Content-Type", ""):
                raise ValueError("Not HTML")
            raw = response.read(10_000_001)
            if len(raw) > 10_000_000:
                raise ValueError("Page exceeds bound")
            if cache_dir is not None:
                asset = cache_dir / hashlib.sha256(raw).hexdigest()
                if not asset.exists():
                    asset.write_bytes(raw)
            parser = Links()
            parser.feed(
                raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            )
            result |= {
                "status": "ok",
                "title": " ".join(parser.title)[:200],
                "html_sha256": hashlib.sha256(raw).hexdigest(),
                "links": sorted(
                    {
                        target
                        for link in parser.links
                        if (target := canonical(urljoin(response.url, link)))
                    }
                ),
            }
    except (HTTPError, URLError, ValueError, TimeoutError, OSError) as exc:
        result |= {"status": "error", "error": str(exc)[:200]}
    return result


def inventory(
    output, budget, *, retry_errors=False, cache_dir=None, backfill_cache=False, workers=4
):
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError("workers must be 1..4")
    previous = (
        json.loads(output.read_text(encoding="utf-8"))
        if output.exists()
        else {"pages": {}, "pending": ROOTS}
    )
    queue = deque(dict.fromkeys(ROOTS + previous["pending"]))
    pages = previous["pages"]
    if retry_errors:
        for url in list(pages):
            if pages[url].get("status") == "error":
                if url not in queue:
                    queue.appendleft(url)
                del pages[url]
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        if backfill_cache:
            for url, page in list(pages.items()):
                sha = page.get("html_sha256")
                if page.get("status") == "ok" and sha and not (cache_dir / sha).is_file():
                    if url not in queue:
                        queue.appendleft(url)
                    del pages[url]
    queued = set(queue)
    attempts = 0
    host_locks = {host: Lock() for host in HOSTS}
    last_start = {}

    def throttle(host):
        # Overlap slow responses, but preserve the original 0.4 s per-host interval.
        with host_locks[host]:
            delay = last_start.get(host, 0) + 0.4 - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            last_start[host] = time.monotonic()

    def checkpoint():
        state = {
            "format": "world-source-inventory-1",
            "pages": pages,
            "pending": list(queue),
            "complete": not queue and all(p.get("status") == "ok" for p in pages.values()),
            "queue_exhausted": not queue,
            "policy": "metadata-only; no article bodies or inferred rights",
        }
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_checkpoint(temporary, output)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        while queue and attempts < budget:
            batch = []
            while queue and len(batch) < workers * 4 and attempts < budget:
                url = queue.popleft()
                queued.discard(url)
                if url not in pages:
                    batch.append(url)
                    attempts += 1
            for result in pool.map(lambda url: read_page(url, cache_dir, throttle), batch):
                pages[result["url"]] = result
                for target in result.get("links", []):
                    if target not in pages and target not in queued and target not in batch:
                        queue.append(target)
                        queued.add(target)
            # A crash can refetch at most 16 pages; source bodies are already cached.
            checkpoint()
    checkpoint()
    print(
        json.dumps(
            {
                "visited": len(pages),
                "pending": len(queue),
                "errors": sum(p.get("status") == "error" for p in pages.values()),
                "queue_exhausted": not queue,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--pages", type=int, default=100)
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--backfill-cache", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.pages <= 10000:
        parser.error("pages must be 1..10000")
    inventory(
        args.output,
        args.pages,
        retry_errors=args.retry_errors,
        cache_dir=args.cache_dir,
        backfill_cache=args.backfill_cache,
        workers=args.workers,
    )
