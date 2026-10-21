"""Tunnel protocol and connection gate, using synthetic cloudflared output only."""

import io
import queue

import pytest

from scripts import tester_host as host


def test_tunnel_uses_http2_and_loopback_without_shell():
    assert host.tunnel_command("C:/Program Files/cloudflared.exe", 12345) == [
        "C:/Program Files/cloudflared.exe",
        "tunnel",
        "--protocol",
        "http2",
        "--url",
        "http://127.0.0.1:12345",
        "--no-autoupdate",
    ]


def test_address_alone_does_not_confirm_connection(capsys):
    urls, connections = queue.Queue(), queue.Queue()
    host.read_tunnel_output(
        io.StringIO("https://example.trycloudflare.com\nprivate raw diagnostic\n"),
        urls,
        connections,
    )
    assert urls.get_nowait() == "https://example.trycloudflare.com"
    with pytest.raises(ValueError, match="до подключения"):
        host.wait_for_tunnel_connection(connections)
    assert not capsys.readouterr().out


def test_registered_connection_opens_gate_without_printing_log_details(capsys):
    urls, connections = queue.Queue(), queue.Queue()
    host.read_tunnel_output(
        io.StringIO(
            "INF Registered tunnel connection connIndex=0 connection=private-id "
            "ip=private-address protocol=http2\n"
        ),
        urls,
        connections,
    )
    host.wait_for_tunnel_connection(connections)
    assert not capsys.readouterr().out


def test_connection_timeout_gives_tcp_hint():
    class Empty:
        def get(self, timeout):
            assert timeout == 90
            raise queue.Empty

    with pytest.raises(ValueError, match="TCP7844"):
        host.wait_for_tunnel_connection(Empty())


@pytest.mark.parametrize(
    "marker", ["failed to dial", "timeout", "no such host", "x509:", "Unable to reach the origin"]
)
def test_only_fixed_error_category_is_printed_once(marker, capsys):
    raw = marker + " secret-path query-token private-address\n"
    host.read_tunnel_output(io.StringIO(raw * 2), queue.Queue(), queue.Queue())
    output = capsys.readouterr().out
    assert output.count("Cloudflare:") == 1
    assert "secret-path" not in output and "query-token" not in output
