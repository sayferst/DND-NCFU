"""Gateway-only HTTP hints for free ngrok endpoints; no provider credentials."""

import re
from urllib.parse import urlsplit


def is_ngrok(url):
    host = urlsplit(url).hostname or ""
    return bool(re.fullmatch(r"[a-z0-9-]+\.(?:ngrok-free\.(?:app|dev)|ngrok\.(?:app|dev))", host))


def gateway_headers(url):
    return {"ngrok-skip-browser-warning": "1"} if is_ngrok(url) else {}


def job_poll_ms(url):
    return 10000 if is_ngrok(url) else 600


def health_interval(url):
    # 8640 idle probes/30days instead of172800 on ngrok's20000-request free quota.
    return 300 if is_ngrok(url) else 15
