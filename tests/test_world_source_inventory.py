"""A complete source inventory must not hide failed pages or follow foreign redirects."""

import hashlib
import importlib.util
import io
import json
from email.message import Message
from pathlib import Path
from urllib.request import Request

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/inventory_world_sources.py"
spec = importlib.util.spec_from_file_location("world_source_inventory_test", SCRIPT)
inventory_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory_module)


class Page(io.BytesIO):
    def __init__(self, url, body):
        super().__init__(body)
        self.url = url
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"


def test_resume_retries_failed_pages_and_retains_local_only_source_cache(tmp_path, monkeypatch):
    root = "https://rpgd100.ru/"
    second = root + "content_pages/equipment"
    output = tmp_path / "inventory.json"
    output.write_text(json.dumps({"pages": {root: {"status": "error"}}, "pending": []}))
    bodies = {
        root: b'<title>World</title><a href="/content_pages/equipment">Equipment</a>',
        second: b"<title>Equipment</title>",
    }
    called = []

    class Opener:
        def open(self, request, timeout):
            called.append(request.full_url)
            return Page(request.full_url, bodies[request.full_url])

    monkeypatch.setattr(inventory_module, "ROOTS", [root])
    monkeypatch.setattr(inventory_module, "build_opener", lambda *a: Opener())
    monkeypatch.setattr(inventory_module.time, "sleep", lambda _: None)
    inventory_module.inventory(output, 10, retry_errors=True, cache_dir=tmp_path / "private")
    result = json.loads(output.read_text())
    assert called == [root, second] and result["complete"] and result["queue_exhausted"]
    assert len(result["pages"]) == 2
    assert "<title>" not in output.read_text()
    for body in bodies.values():
        assert (tmp_path / "private" / hashlib.sha256(body).hexdigest()).read_bytes() == body


def test_failed_page_prevents_complete_claim_even_when_queue_exhausted(tmp_path, monkeypatch):
    class Opener:
        def open(self, request, timeout):
            raise TimeoutError("network unavailable")

    monkeypatch.setattr(inventory_module, "ROOTS", ["https://rpgd100.ru/"])
    monkeypatch.setattr(inventory_module, "build_opener", lambda *a: Opener())
    monkeypatch.setattr(inventory_module.time, "sleep", lambda _: None)
    output = tmp_path / "inventory.json"
    inventory_module.inventory(output, 1)
    result = json.loads(output.read_text())
    assert result["queue_exhausted"] and not result["complete"]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "https://127.0.0.1/",
        "https://evil.example/",
        "https://rpgd100.ru/login",
    ],
)
def test_redirect_is_checked_before_network_request(url):
    with pytest.raises(ValueError, match="outside"):
        inventory_module.SourceRedirects().redirect_request(
            Request("https://rpgd100.ru/"), None, 302, "Found", {}, url
        )


def test_unicode_spaces_and_http_links_are_encoded_and_upgraded():
    assert inventory_module.canonical("http://dnd.su/class/Царство теней [Realm]#x") == (
        "https://dnd.su/class/%D0%A6%D0%B0%D1%80%D1%81%D1%82%D0%B2%D0%BE%20"
        "%D1%82%D0%B5%D0%BD%D0%B5%D0%B9%20%5BRealm%5D"
    )
    assert inventory_module.canonical("https://dnd.su/a\nb") is None


@pytest.mark.parametrize("permanent", [False, True])
def test_checkpoint_retries_temporary_windows_reader_lock_without_losing_old_state(
    tmp_path, monkeypatch, permanent
):
    output, temporary = tmp_path / "state.json", tmp_path / "state.tmp"
    output.write_text('{"old":true}', encoding="utf-8")
    temporary.write_text('{"new":true}', encoding="utf-8")
    original = Path.replace
    calls = []

    def locked(path, target):
        assert path == temporary and target == output
        calls.append(path)
        if permanent or len(calls) < 3:
            raise PermissionError("Simulated Windows reader lock")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", locked)
    monkeypatch.setattr(inventory_module.time, "sleep", lambda _: None)
    if permanent:
        with pytest.raises(PermissionError):
            inventory_module.replace_checkpoint(temporary, output)
        assert len(calls) == 10
        assert json.loads(output.read_text()) == {"old": True}
        assert json.loads(temporary.read_text()) == {"new": True}
    else:
        inventory_module.replace_checkpoint(temporary, output)
        assert len(calls) == 3 and not temporary.exists()
        assert json.loads(output.read_text()) == {"new": True}
