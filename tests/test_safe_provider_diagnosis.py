"""Failed metadata can explain HTTP400 without disclosing a provider reply or secret."""

import json

import pytest
from test_host_metadata_errors import KEY, upstream

from scripts.tester_host import diagnose_provider
from server.metadata_errors import classify


@pytest.mark.parametrize(
    "message,reason",
    [
        (
            "Master keys are not supported for this endpoint. Use a regular API key.",
            "master_key_not_supported",
        ),
        ("This endpoint requires a master key", "master_key_required"),
        ("Invalid API key", "key_rejected"),
        ("invalid_api_key", "key_rejected"),
        ("API key is expired", "key_inactive"),
        ("API key not found", "key_rejected"),
        ("Missing Authorization header", "authorization_missing"),
        ("Invalid Authorization header format, expected Bearer", "authorization_format"),
        ("Missing API key", "authorization_missing"),
        ("Unexpected end of JSON input", "body_rejected"),
        ("Request body is required", "body_rejected"),
        ("Unsupported endpoint", "operation_unavailable"),
        ("Insufficient balance", "quota_rejected"),
        ("Access denied", "access_denied"),
        ("Unknown failure with owner-secret-not-for-output", "unrecognized"),
    ],
)
def test_provider_message_maps_only_to_fixed_label(message, reason):
    raw = json.dumps({"error": {"message": message, "account": "private@example.org"}}).encode()
    assert classify(raw) == (reason, "json")


def test_generic_invalid_request_type_does_not_mean_key_is_invalid():
    assert (
        classify(
            json.dumps(
                {"error": {"message": "Missing API key", "type": "invalid_request_error"}}
            ).encode()
        )[0]
        == "authorization_missing"
    )


@pytest.mark.parametrize(
    "raw,reason,format",
    [
        (b"Invalid API key", "key_rejected", "text"),
        (b"<!doctype html><html>Invalid API key secret</html>", "unrecognized", "html"),
        (b"not json with owner-secret-not-for-output", "unrecognized", "text"),
        (b"{", "unrecognized", "text"),
        (b"[null]", "unrecognized", "json"),
    ],
)
def test_plain_text_html_and_invalid_json_never_echo_body(raw, reason, format):
    assert classify(raw) == (reason, format)


def test_failed_metadata_report_contains_only_safe_labels(monkeypatch):
    raw = json.dumps(
        {
            "error": {
                "message": "Invalid API key: owner-secret-not-for-output",
                "code": "owner-secret-not-for-output",
                "request_id": "private-id",
            },
            "email": "private@example.org",
        }
    ).encode()
    provider, calls = upstream(monkeypatch, raw, status=400)
    report = diagnose_provider(provider)
    encoded = json.dumps(report)
    assert report["http_status"] == 400 and report["provider_reason"] == "key_rejected"
    assert report["reason_is_inferred"] is True
    assert report["response_format"] == "json" and report["paid_requests"] == 0
    assert report["address_published"] is False and report["tunnel_started"] is False
    assert "owner-secret" not in encoded and "private" not in encoded
    assert calls[0].reads == 1 and calls[0].closed


def test_error_body_read_is_bounded_and_generated_errors_still_unread(monkeypatch):
    raw = b"x" * 8192 + b"Invalid API key: owner-secret-not-for-output"
    provider, calls = upstream(monkeypatch, raw, status=400)
    report = diagnose_provider(provider)
    assert report["provider_reason"] == "unrecognized" and calls[0].reads == 1
    provider, calls = upstream(monkeypatch, b"owner-secret-not-for-output", status=401)
    assert diagnose_provider(provider)["http_status"] == 401 and calls[0].reads == 0


def test_successful_metadata_and_policy_errors_do_not_start_generation(monkeypatch):
    provider, calls = upstream(monkeypatch, json.dumps({"data": KEY}).encode())
    assert diagnose_provider(provider)["ok"] is True
    provider, calls = upstream(monkeypatch, json.dumps({"data": KEY | {"limit": None}}).encode())
    report = diagnose_provider(provider)
    assert report["ok"] is False and report["provider_reason"] == "allowance_not_confirmed"
    assert "месячный лимит" in report["message"] and report["paid_requests"] == 0


def test_replacing_revoked_key_changes_only_owner_credential(tmp_path, monkeypatch, capsys):
    from scripts import tester_host

    seen = {}
    monkeypatch.setattr(tester_host.getpass, "getpass", lambda _: "new-owner-secret-do-not-print")
    monkeypatch.setattr(tester_host, "save_secret", lambda path, value: seen.update({path: value}))
    old = tmp_path / "signing-key.bin"
    old.write_bytes(b"fixture-other-key-untouched")
    tester_host.replace_owner_key(tmp_path)
    assert seen == {tmp_path / "routerai-key.bin": "new-owner-secret-do-not-print"}
    assert old.read_bytes() == b"fixture-other-key-untouched"
    assert "new-owner-secret" not in capsys.readouterr().out


def test_invalid_replacement_preserves_old_key(tmp_path, monkeypatch):
    from scripts import tester_host

    monkeypatch.setattr(tester_host.getpass, "getpass", lambda _: "Bearer wrong format")
    monkeypatch.setattr(
        tester_host, "save_secret", lambda *_: pytest.fail("must not replace old key")
    )
    with pytest.raises(ValueError):
        tester_host.replace_owner_key(tmp_path)


def test_cli_key_and_diagnose_never_open_quota_database(tmp_path, monkeypatch, capsys):
    import sys
    from types import SimpleNamespace

    from scripts import tester_host

    monkeypatch.setattr(
        tester_host, "os", SimpleNamespace(name="nt", environ={"LOCALAPPDATA": str(tmp_path)})
    )
    monkeypatch.setattr(
        tester_host,
        "Store",
        lambda *_a, **_k: pytest.fail("no grant database on credential operations"),
    )
    monkeypatch.setattr(tester_host, "replace_owner_key", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["tester_host.py", "key"])
    assert tester_host.main() == 0
    monkeypatch.setattr(tester_host, "load_secret", lambda _: "fixture-owner-key")
    monkeypatch.setattr(
        tester_host, "diagnose_provider", lambda _: {"ok": False, "paid_requests": 0}
    )
    monkeypatch.setattr(sys, "argv", ["tester_host.py", "diagnose"])
    assert tester_host.main() == 2
    assert "fixture-owner-key" not in capsys.readouterr().out


def test_unreadable_optional_error_body_preserves_http400(monkeypatch):
    provider, calls = upstream(monkeypatch, b"", status=400)
    # Connection type is instantiated inside request; replace getresponse with a failure on read.
    original = __import__("server.gateway", fromlist=["http"]).http.client.HTTPSConnection

    def connection(*args, **kwargs):
        result = original(*args, **kwargs)

        def unreadable(_maximum):
            raise TimeoutError("owner-secret-not-for-output")

        result.read = unreadable
        return result

    monkeypatch.setattr("server.gateway.http.client.HTTPSConnection", connection)
    report = diagnose_provider(provider)
    assert report["http_status"] == 400 and report["response_format"] == "unavailable"
    assert "owner-secret" not in json.dumps(report) and calls[0].closed


def test_unrecognized_exception_attributes_cannot_be_echoed_by_report():
    from server.gateway import Denied

    class Broken:
        def request(self, _route):
            error = Denied(503, "upstream_http_400")
            error.provider_reason = "owner-secret-not-for-output"
            error.response_format = "private@example.org"
            raise error

    report = diagnose_provider(Broken())
    assert (
        report["provider_reason"] == "unrecognized" and report["response_format"] == "unavailable"
    )
    assert "owner-secret" not in json.dumps(report) and "private@" not in json.dumps(report)
