"""Network is simulated here; actual downloaded tokenizer parity is reported separately."""

import hashlib
from io import BytesIO

import pytest

from training import fetch_faun_tokenizer as module


def test_fetch_whitelist_and_hashes_without_weight_requests(tmp_path, monkeypatch):
    raw = b"authored-tokenizer-fixture"
    monkeypatch.setattr(
        module, "HASHES", {n: hashlib.sha256(raw).hexdigest() for n in module.HASHES}
    )
    urls = []

    def opener(url, *, timeout):
        urls.append(url)
        return BytesIO(raw)

    path = tmp_path / "tokenizer"
    result = module.fetch(path, opener=opener)
    assert len(urls) == 4 and not result["weights_downloaded"]
    assert all(module.REVISION in u for u in urls)
    assert not any(".safetensors" in u or ".gguf" in u for u in urls)
    with pytest.raises(FileExistsError):
        module.fetch(path, opener=opener)


def test_bad_download_hash_stops_without_success_manifest(tmp_path):
    path = tmp_path / "bad"
    with pytest.raises(ValueError, match="size/hash differs"):
        module.fetch(path, opener=lambda *args, **kwargs: BytesIO(b"bad"))
    assert not (path / "download-manifest.json").exists()
    assert not (path / "tokenizer.json").exists()
