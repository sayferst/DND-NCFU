"""Owner-only DNS-over-HTTPS bootstrap for cloudflared; no system DNS changes."""

import ipaddress
import json
import socket
import urllib.request
from urllib.parse import urlencode

from rpg_vkr.discovery import NoRedirect

RESOLVERS = (
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
    "https://1.1.1.1/dns-query",
)
EDGE_NAMES = ("region1.v2.argotunnel.com", "region2.v2.argotunnel.com")
# Cloudflare's published firewall/dig examples; used only when HTTPS DNS fails.
# https://developers.cloudflare.com/cloudflare-one/networks/connectors/
# cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/
BOOTSTRAP = {
    EDGE_NAMES[0]: ("198.41.192.167:7844", "198.41.192.67:7844"),
    EDGE_NAMES[1]: ("198.41.200.13:7844", "198.41.200.193:7844"),
}


def lookup_edge(resolver, name):
    if resolver not in RESOLVERS or name not in EDGE_NAMES:
        raise ValueError("Unsupported tunnel DNS query")
    request = urllib.request.Request(
        resolver + "?" + urlencode({"name": name, "type": "A"}),
        headers={"Accept": "application/dns-json"},
    )
    with urllib.request.build_opener(NoRedirect).open(request, timeout=8) as response:
        if response.status != 200:
            raise ValueError("Tunnel DNS HTTP error")
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError("Tunnel DNS reply too large")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("Status") != 0:
        raise ValueError("Tunnel DNS failure")
    answers = value.get("Answer")
    if not isinstance(answers, list) or len(answers) > 100:
        raise ValueError("Tunnel DNS answers missing")
    result = []
    for answer in answers:
        if (
            not isinstance(answer, dict)
            or answer.get("type") != 1
            or str(answer.get("name", "")).rstrip(".").lower() != name
        ):
            continue
        address = ipaddress.ip_address(answer.get("data", ""))
        if address.version != 4 or not address.is_global:
            raise ValueError("Nonpublic tunnel DNS answer")
        endpoint = str(address) + ":7844"
        if endpoint not in result:
            result.append(endpoint)
    if not result:
        raise ValueError("Tunnel DNS addresses missing")
    return result[:2]


def resolve_tunnel_edges():
    # Resolve the same two service targets used by cloudflared, through HTTPS443.
    # --edge takes IP:port and avoids the OS SRV/A lookup. cloudflared still verifies
    # Cloudflare's TLS server name; no origin/TLS verification flags are disabled.
    addresses = []
    for name in EDGE_NAMES:
        for resolver in RESOLVERS:
            try:
                addresses.extend(lookup_edge(resolver, name))
                break
            except (OSError, ValueError, TypeError, RecursionError):
                continue
        else:
            print(
                "DNS-over-HTTPS недоступен для региона. "
                "Использую резервные адреса из публичного списка Cloudflare.",
                flush=True,
            )
            addresses.extend(BOOTSTRAP[name])
    return tuple(dict.fromkeys(addresses))


def reachable_edges(edges):
    available = []
    for edge in edges:
        address, port = edge.rsplit(":", 1)
        # All edges originate from lookup_edge or the fixed official bootstrap.
        parsed = ipaddress.ip_address(address)
        if parsed.version != 4 or not parsed.is_global or port != "7844":
            raise ValueError("Invalid tunnel TCP target")
        try:
            with socket.create_connection((str(parsed), 7844), timeout=3):
                available.append(edge)
        except OSError:
            continue
    if not available:
        raise ValueError(
            "DNS обойдён, но TCP-соединение с узлами Cloudflare на порту7844 "
            "не устанавливается. Проверьте исходящий доступ cloudflared.exe "
            "или используйте другую сеть/VPN. Входящие порты открывать не нужно."
        )
    return tuple(available)
