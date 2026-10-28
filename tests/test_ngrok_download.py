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


@pytest.mark.parametrize("failure", ["connect", "body", "short_body"])
def test_python_transport_failure_restarts_full_download_with_windows(
    tmp_path, monkeypatch, failure
):
    class BrokenResponse(Response):
        headers = {"Content-Length": "9999"}

        def read(self, n):
            if failure == "body":
                raise TimeoutError("body stalled after HTTP200")
            return super().read(n)

    def request(*args, **kwargs):
        if failure == "connect":
            raise OSError("Python transport unavailable")
        return BrokenResponse(b"partial")

    monkeypatch.setattr(download, "WINDOWS", True)
    monkeypatch.setattr(download.urllib.request, "urlopen", request)
    calls = []
    monkeypatch.setattr(download, "windows_payload", lambda p: (calls.append(p), archive())[1])
    verified = []
    monkeypatch.setattr(download, "verify_publisher", lambda p: verified.append(p.read_bytes()))
    target = tmp_path / "candidate.exe"
    download.download_agent(target)
    assert calls == [target] and verified == [b"MZ-test-binary"]


@pytest.mark.parametrize("outcome", ["valid", "failed", "oversize"])
def test_windows_transport_bounds_secrets_and_temporary_archive(tmp_path, monkeypatch, outcome):
    monkeypatch.setenv("NGROK_AUTHTOKEN", "private-token")
    monkeypatch.setenv("PSModulePath", "incompatible-modules")
    target = tmp_path / "candidate.exe"
    payload = b"zip"
    if outcome == "oversize":
        monkeypatch.setattr(download, "MAX_ARCHIVE", 2)

    def run(args, **kwargs):
        assert kwargs["timeout"] == 240
        assert "NGROK_AUTHTOKEN" not in kwargs["env"] and "PSModulePath" not in kwargs["env"]
        script = args[-1]
        assert "ResponseUri.Scheme -ne 'https'" in script
        assert "ServerCertificateValidationCallback" not in script
        assert f"$total -gt {download.MAX_ARCHIVE}" in script
        Path(kwargs["env"]["DND_NGROK_ZIP"]).write_bytes(payload)
        return SimpleNamespace(returncode=1 if outcome == "failed" else 0)

    monkeypatch.setattr(download.subprocess, "run", run)
    if outcome == "valid":
        assert download.windows_payload(target) == payload
    else:
        with pytest.raises(ValueError):
            download.windows_payload(target)
    assert not target.with_suffix(".download.zip").exists()
