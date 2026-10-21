"""Owner diagnostics keep HTTP/transport/policy failures distinct without disclosing secrets."""

import json
import ssl

import pytest
from test_gateway import FakeUpstream

from scripts.tester_host import check_provider
from server.gateway import Denied, Gateway, Store, Upstream

KEY = {
    "disabled": False,
    "limit": 100,
    "limit_remaining": 100,
    "usage_monthly": 0,
    "limit_reset": "monthly",
}


def upstream(monkeypatch, response, *, status=200, failure=None):
    calls = []

    class Connection:
        def __init__(self, host, **options):
            self.timeout = options["timeout"]
            self.status = status
            self.closed = False
            self.reads = 0
            calls.append(self)

        def request(self, method, path, body, headers):
            self.method, self.path = method, path
            assert headers["Authorization"] == "Bearer owner-secret-not-for-output"
            assert body is None
            if failure:
                raise failure

        def getresponse(self):
            return self

        def read(self, maximum):
            self.reads += 1
            return response[:maximum]

        def close(self):
            self.closed = True

    monkeypatch.setattr("server.gateway.http.client.HTTPSConnection", Connection)
    return Upstream("owner-secret-not-for-output"), calls


@pytest.mark.parametrize("value", [{"data": KEY}, [{"data": KEY}], [KEY]])
def test_documented_key_wrappers_survive_transport_and_owner_validation(
    tmp_path, monkeypatch, value
):
    provider, calls = upstream(monkeypatch, json.dumps(value).encode())
    fake = FakeUpstream()
    original = fake.request
    fake.request = (
        lambda route, body=None: provider.request(route)
        if route == "key"
        else original(route, body)
    )
    check_provider(Gateway(Store(tmp_path / "db"), fake))
    assert not fake.posts
    assert calls[0].method == "GET" and calls[0].path == "/api/v1/key"
    assert calls[0].timeout == 20 and calls[0].closed


@pytest.mark.parametrize("status", [400, 401, 403, 402, 429, 500])
def test_http_status_survives_to_safe_owner_diagnostic(tmp_path, monkeypatch, status):
    provider, calls = upstream(monkeypatch, b"owner-secret-not-for-output", status=status)
    with pytest.raises(ValueError) as captured:
        check_provider(Gateway(Store(tmp_path / "db"), provider))
    message = str(captured.value)
    assert str(status) in message
    assert "owner-secret" not in message and "не запускалась" in message
    assert calls[0].closed and calls[0].reads == 0


@pytest.mark.parametrize(
    "failure,expected",
    [
        (ssl.SSLError("owner-secret-not-for-output"), "TLS"),
        (TimeoutError("owner-secret-not-for-output"), "время ожидания"),
        (OSError("owner-secret-not-for-output"), "соединиться"),
    ],
)
def test_transport_failures_are_distinct_and_never_echo_exception_text(
    tmp_path, monkeypatch, failure, expected
):
    provider, calls = upstream(monkeypatch, b"", failure=failure)
    with pytest.raises(ValueError) as captured:
        check_provider(Gateway(Store(tmp_path / "db"), provider))
    assert expected in str(captured.value) and "owner-secret" not in str(captured.value)
    assert calls[0].closed


@pytest.mark.parametrize(
    "edit,expected",
    [
        ({"disabled": True}, "выключен"),
        ({"limit": None}, "Задайте его в кабинете"),
        ({"limit": 0}, "положительный месячный"),
        ({"limit": 3000}, "не более 2000"),
        ({"limit_reset": "daily"}, "не дневной"),
        ({"usage_monthly": 100}, "исчерпан"),
        ({"limit_remaining": 0}, "исчерпан"),
        ({"limit": "owner-secret-not-for-output"}, "Неверная сумма"),
    ],
)
def test_exact_key_policy_reason_is_preserved_without_relaxing_guard(
    tmp_path, monkeypatch, edit, expected
):
    provider, calls = upstream(monkeypatch, json.dumps({"data": KEY | edit}).encode())
    with pytest.raises(ValueError) as captured:
        check_provider(Gateway(Store(tmp_path / "db"), provider))
    assert expected in str(captured.value) and "owner-secret" not in str(captured.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "raw,expected",
    [(b"not JSON owner-secret", "upstream_invalid_json"), (b"x" * 65537, "upstream_response_size")],
    ids=("invalid-json", "oversized"),
)
def test_invalid_metadata_is_bounded_and_not_printed(monkeypatch, raw, expected):
    provider, calls = upstream(monkeypatch, raw)
    with pytest.raises(Denied, match=expected):
        provider.request("key")
    assert calls[0].closed
