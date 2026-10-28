"""No real downloads or executable launches in these admission tests."""

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import ngrok_download as download


def archive(name="ngrok.exe", body=b"MZ-test-binary"):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as z:
        z.writestr(name, body)
    return result.getvalue()


class Response(io.BytesIO):
    def geturl(self):
        return download.URL


def test_official_archive_is_verified_before_admission(tmp_path, monkeypatch):
    calls = []

    def request(url, **kwargs):
        assert url == download.URL and kwargs["timeout"] == 30
        return Response(archive())

    monkeypatch.setattr(download.urllib.request, "urlopen", request)
    monkeypatch.setattr(download, "verify_publisher", lambda p: calls.append(p.read_bytes()))
    target = tmp_path / "candidate.exe"
    download.download_agent(target)
    assert calls == [b"MZ-test-binary"]


@pytest.mark.parametrize("case", ["oversize", "traversal", "not_pe", "bad_signature"])
def test_invalid_download_never_leaves_an_executable(tmp_path, monkeypatch, case):
    data = archive()
    if case == "oversize":
        monkeypatch.setattr(download, "MAX_ARCHIVE", 5)
    elif case == "traversal":
        data = archive("../escape.exe")
    elif case == "not_pe":
        data = archive(body=b"invalid")
    monkeypatch.setattr(download.urllib.request, "urlopen", lambda *a, **k: Response(data))

    def reject(path):
        raise ValueError("Untrusted publisher")

    monkeypatch.setattr(download, "verify_publisher", reject)
    target = tmp_path / "candidate.exe"
    with pytest.raises(ValueError, match="официальный"):
        download.download_agent(target)
    assert not target.exists() and not (tmp_path.parent / "escape.exe").exists()


@pytest.mark.parametrize("relative", [False, True])
def test_signature_requires_windows_trust_and_ngrok_publisher(tmp_path, monkeypatch, relative):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NGROK_AUTHTOKEN", "private-token")
    monkeypatch.setenv("PSModulePath", "incompatible-PowerShell7-modules")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert "NGROK_AUTHTOKEN" not in kwargs["env"]
        assert "PSModulePath" not in kwargs["env"]
        assert kwargs["env"]["DND_NGROK_VERIFY_PATH"] == str(tmp_path / "candidate.exe")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(download.subprocess, "run", run)
    with pytest.raises(ValueError, match="Подпись"):
        download.verify_publisher(Path("candidate.exe") if relative else tmp_path / "candidate.exe")
    assert "Get-AuthenticodeSignature" in calls[0][-1]
    assert "'Valid'" in calls[0][-1] and "'ngrok, Inc.'" in calls[0][-1]
