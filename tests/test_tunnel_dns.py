"""DoH and numeric cloudflared edges; fake HTTP only, no external DNS/tunnel."""

import json
import urllib.error

import pytest

from scripts import tester_host
from scripts import tunnel_dns as dns


def answer(name=dns.EDGE_NAMES[0], data="198.41.192.167"):
    return {"Status": 0, "Answer": [{"name": name + ".", "type": 1, "data": data}]}


def opener(monkeypatch, value):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    requests = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            assert size == 65537
            return raw[:size]

    class Opener:
        def open(self, request, timeout):
            assert timeout == 8
            requests.append(request)
            return Response()

    monkeypatch.setattr(dns.urllib.request, "build_opener", lambda handler: Opener())
    return requests


def test_https_dns_query_has_no_authorization_and_yields_numeric_edges(monkeypatch):
    requests = opener(monkeypatch, answer())
    assert dns.lookup_edge(dns.RESOLVERS[0], dns.EDGE_NAMES[0]) == ["198.41.192.167:7844"]
    request = requests[0]
    assert request.full_url.startswith("https://cloudflare-dns.com/dns-query?")
    assert request.get_method() == "GET" and request.data is None
    assert not request.has_header("Authorization")
    command = tester_host.tunnel_command("cloudflared", 1234, ["198.41.192.167:7844"])
    assert command[-2:] == ["--edge", "198.41.192.167:7844"]
    assert "--no-tls-verify" not in command


@pytest.mark.parametrize(
    "data", ["127.0.0.1", "10.0.0.1", "::1", "--no-tls-verify", "198.41.192.167:443"]
)
def test_dns_rejects_nonpublic_or_non_address_answers(monkeypatch, data):
    opener(monkeypatch, answer(data=data))
    with pytest.raises(ValueError):
        dns.lookup_edge(dns.RESOLVERS[0], dns.EDGE_NAMES[0])


@pytest.mark.parametrize(
    "value",
    [{"Status": 3}, {"Status": 0, "Answer": []}, [], b"x" * 65537, answer(name="attacker.example")],
    ids=["dns-error", "empty-answer", "wrong-type", "oversized", "wrong-name"],
)
def test_invalid_dns_reply_is_not_used(monkeypatch, value):
    opener(monkeypatch, value)
    with pytest.raises(ValueError):
        dns.lookup_edge(dns.RESOLVERS[0], dns.EDGE_NAMES[0])


def test_dns_falls_back_per_region_and_keeps_both_regions(monkeypatch):
    calls = []

    def lookup(resolver, name):
        calls.append((resolver, name))
        if resolver == dns.RESOLVERS[0]:
            raise urllib.error.URLError("private DNS detail")
        return ["198.41.192.167:7844" if name == dns.EDGE_NAMES[0] else "198.41.200.13:7844"]

    monkeypatch.setattr(dns, "lookup_edge", lookup)
    assert dns.resolve_tunnel_edges() == ("198.41.192.167:7844", "198.41.200.13:7844")
    assert len(calls) == 4


def test_all_dns_failures_use_official_numeric_bootstrap(monkeypatch, capsys):
    def failure(*args):
        raise urllib.error.URLError("private network detail")

    monkeypatch.setattr(dns, "lookup_edge", failure)
    assert dns.resolve_tunnel_edges() == tuple(
        edge for name in dns.EDGE_NAMES for edge in dns.BOOTSTRAP[name]
    )
    output = capsys.readouterr().out
    assert "публичного списка Cloudflare" in output
    assert "private network detail" not in output


@pytest.mark.parametrize(
    "edge", ["localhost:7844", "127.0.0.1:7844", "198.41.192.167:443", "--help"]
)
def test_tunnel_argument_revalidates_dns_endpoints(edge):
    with pytest.raises(ValueError):
        tester_host.tunnel_command("cloudflared", 1234, [edge])


def test_tcp_probe_uses_numeric_addresses_and_filters_unreachable_edges(monkeypatch):
    calls = []

    class Connected:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def connect(target, timeout):
        calls.append((target, timeout))
        if target[0] == "198.41.192.167":
            raise TimeoutError
        return Connected()

    monkeypatch.setattr(dns.socket, "create_connection", connect)
    assert dns.reachable_edges(("198.41.192.167:7844", "198.41.200.13:7844")) == (
        "198.41.200.13:7844",
    )
    assert calls == [(("198.41.192.167", 7844), 3), (("198.41.200.13", 7844), 3)]


def test_unreachable_tcp_is_distinct_from_dns_failure(monkeypatch):
    def fail(*a, **k):
        raise OSError("private detail")

    monkeypatch.setattr(dns.socket, "create_connection", fail)
    with pytest.raises(ValueError, match="DNS обойдён") as error:
        dns.reachable_edges(("198.41.192.167:7844",))
    assert "private detail" not in str(error.value)
