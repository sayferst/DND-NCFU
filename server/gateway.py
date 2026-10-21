"""Small stdlib HTTPS gateway. No game engine, arbitrary proxy, retries or prompt logs."""

import argparse
import base64
import hashlib
import http.client
import ipaddress
import json
import os
import re
import secrets
import socket
import sqlite3
import ssl
import threading
import time
from contextlib import closing
from decimal import ROUND_CEILING, Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

TEXT_MODEL = "deepseek/deepseek-v4-flash-latest"
RECRAFT = "recraft/recraft-v4.1-flash"
FLUX = "black-forest-labs/flux-3-image-klein"
IMAGE_CAPS = {RECRAFT: 5_000_000, FLUX: 10_000_000}
MAX_BODY = 24 * 1024 * 1024
MAX_REPLY = 40 * 1024 * 1024
STAGES = {"director", "story_result", "challenge", "world_plan", "world_seed"}


class Denied(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def micros(value):
    if isinstance(value, bool):
        raise ValueError("amount")
    number = Decimal(str(value))
    if not number.is_finite() or not 0 <= number <= 10**9:
        raise ValueError("amount")
    return int((number * 1000000).to_integral_value(rounding=ROUND_CEILING))


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    def __init__(self, path, global_budget=100_000_000, clock=time.time):
        self.path, self.global_budget, self.clock = Path(path), global_budget, clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS testers(
                    id TEXT PRIMARY KEY, hash TEXT UNIQUE NOT NULL, expires REAL NOT NULL,
                    budget INTEGER NOT NULL, requests INTEGER NOT NULL, worlds INTEGER NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS calls(
                    tester TEXT NOT NULL, id TEXT NOT NULL, created REAL NOT NULL,
                    reserve INTEGER NOT NULL, actual INTEGER, kind TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending', PRIMARY KEY(tester,id));
                CREATE INDEX IF NOT EXISTS calls_created ON calls(tester,created);
                CREATE TABLE IF NOT EXISTS activations(
                    hash TEXT PRIMARY KEY, tester TEXT UNIQUE NOT NULL, installation TEXT);
                CREATE TABLE IF NOT EXISTS control(id INTEGER PRIMARY KEY, halted INTEGER NOT NULL);
                INSERT OR IGNORE INTO control VALUES(1,0);
            """)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def issue(self, identity, *, days=7, budget=10_000_000, requests=50, worlds=2):
        if (
            not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", identity)
            or not 1 <= days <= 90
            or not 0 < budget <= self.global_budget
            or not 0 < requests <= 10000
            or not 0 <= worlds <= requests
        ):
            raise ValueError("Invalid grant")
        token = secrets.token_urlsafe(32)
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT INTO testers(id,hash,expires,budget,requests,worlds) VALUES(?,?,?,?,?,?)",
                (identity, digest(token), self.clock() + days * 86400, budget, requests, worlds),
            )
        return token

    def bootstrap(self, identity, **limits):
        # Unclaimed grants cannot authenticate to generation endpoints.
        self.issue(identity, **limits)
        code = secrets.token_urlsafe(32)
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO activations(hash,tester) VALUES(?,?)", (digest(code), identity))
        return code

    def activate(self, code, installation):
        if not all(
            isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_-]{40,100}", v)
            for v in (code, installation)
        ):
            raise Denied(401, "activation_required")
        # Same installation can recover a lost activation reply, without storing raw tokens.
        token = hashlib.sha256(
            ("DND-activation-v1:" + code + ":" + installation).encode()
        ).hexdigest()
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT a.*,t.revoked,t.expires FROM activations a JOIN testers t "
                "ON t.id=a.tester WHERE a.hash=?",
                (digest(code),),
            ).fetchone()
            if row is None or row["revoked"] or row["expires"] <= self.clock():
                raise Denied(401, "access_expired_or_revoked")
            if row["installation"] and row["installation"] != digest(installation):
                raise Denied(409, "already_activated")
            db.execute(
                "UPDATE activations SET installation=? WHERE hash=?",
                (digest(installation), digest(code)),
            )
            db.execute("UPDATE testers SET hash=? WHERE id=?", (digest(token), row["tester"]))
        return {"token": token}

    def extend(self, identity, days):
        if type(days) is not int or not 1 <= days <= 90:
            raise ValueError("days must be 1..90")
        with closing(self.connect()) as db, db:
            changed = db.execute(
                "UPDATE testers SET expires=MAX(expires,?)+? WHERE id=? AND revoked=0",
                (self.clock(), days * 86400, identity),
            ).rowcount
            if not changed:
                raise ValueError("Unknown or revoked grant")

    def revoke(self, identity):
        with closing(self.connect()) as db, db:
            db.execute("UPDATE testers SET revoked=1 WHERE id=?", (identity,))

    def identity(self, token):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", token):
            raise Denied(401, "activation_required")
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM testers WHERE hash=?", (digest(token),)).fetchone()
        if row is None or row["revoked"] or row["expires"] <= self.clock():
            raise Denied(401, "access_expired_or_revoked")
        return dict(row)

    def allowance(self, token):
        user = self.identity(token)
        with closing(self.connect()) as db:
            used = db.execute(
                "SELECT COALESCE(SUM(COALESCE(actual,reserve)),0) FROM calls WHERE tester=?",
                (user["id"],),
            ).fetchone()[0]
            global_used = db.execute(
                "SELECT COALESCE(SUM(COALESCE(actual,reserve)),0) FROM calls"
            ).fetchone()[0]
        remaining = max(0, min(user["budget"] - used, self.global_budget - global_used))
        limit = min(user["budget"], 2_000_000_000)
        return {
            "data": {
                "disabled": False,
                "limit": limit / 1e6,
                "limit_reset": "monthly",
                "usage_monthly": min(used, limit) / 1e6,
                "limit_remaining": remaining / 1e6,
            }
        }

    def reserve(self, token, identity, expected, kind):
        user = self.identity(token)
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", identity or ""):
            raise Denied(400, "request_id_required")
        if type(expected) is not int or expected <= 0:
            raise Denied(503, "price_unavailable")
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            # Re-check revocation under the same transaction as budget reservation.
            current = db.execute("SELECT * FROM testers WHERE id=?", (user["id"],)).fetchone()
            if current["revoked"] or current["expires"] <= self.clock():
                raise Denied(401, "access_expired_or_revoked")
            if db.execute("SELECT halted FROM control WHERE id=1").fetchone()[0]:
                raise Denied(503, "billing_review_required")
            if db.execute(
                "SELECT 1 FROM calls WHERE tester=? AND id=?", (user["id"], identity)
            ).fetchone():
                raise Denied(409, "request_already_received")
            rows = db.execute("SELECT * FROM calls WHERE tester=?", (user["id"],)).fetchall()
            used = sum(r["actual"] if r["actual"] is not None else r["reserve"] for r in rows)
            total = db.execute(
                "SELECT COALESCE(SUM(COALESCE(actual,reserve)),0) FROM calls"
            ).fetchone()[0]
            if used + expected > current["budget"] or total + expected > self.global_budget:
                raise Denied(429, "budget_exhausted")
            if (
                len(rows) >= current["requests"]
                or sum(r["created"] > self.clock() - 60 for r in rows) >= 6
            ):
                raise Denied(429, "request_limit")
            if any(r["state"] == "pending" for r in rows):
                raise Denied(429, "request_in_progress")
            if kind == "world_seed" and sum(r["kind"] == kind for r in rows) >= current["worlds"]:
                raise Denied(429, "world_limit")
            db.execute(
                "INSERT INTO calls(tester,id,created,reserve,kind) VALUES(?,?,?,?,?)",
                (user["id"], identity, self.clock(), expected, kind),
            )
        return user["id"]

    def settle(self, user, identity, actual, *, succeeded):
        with closing(self.connect()) as db, db:
            row = db.execute(
                "SELECT reserve FROM calls WHERE tester=? AND id=?", (user, identity)
            ).fetchone()
            if actual is not None and actual > row[0]:
                db.execute("UPDATE control SET halted=1 WHERE id=1")
            db.execute(
                "UPDATE calls SET actual=?,state=? WHERE tester=? AND id=?",
                (actual, "done" if succeeded else "uncertain", user, identity),
            )

    def summary(self):
        with closing(self.connect()) as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT t.id,t.expires,t.budget,t.requests,t.worlds,t.revoked,"
                    "COUNT(c.id) AS calls,"
                    "COALESCE(SUM(COALESCE(c.actual,c.reserve)),0) AS committed "
                    "FROM testers t LEFT JOIN calls c ON t.id=c.tester GROUP BY t.id"
                )
            ]


class Upstream:
    def __init__(self, key):
        if not key or any(c.isspace() for c in key):
            raise ValueError("Set DND_ROUTERAI_KEY on the server")
        self.key = key

    def request(self, route, body=None):
        if route not in {"key", "models", "chat/completions", "images"}:
            raise Denied(400, "route")
        connection = http.client.HTTPSConnection(
            "routerai.ru",
            timeout=20
            if route in {"key", "models"}
            else 900
            if route == "chat/completions"
            else 180,
        )
        try:
            headers = {"Accept": "application/json"}
            if route != "models":
                headers["Authorization"] = "Bearer " + self.key
            if body is not None:
                headers["Content-Type"] = "application/json"
            connection.request(
                "POST" if body is not None else "GET",
                "/api/v1/" + route,
                json.dumps(body).encode() if body is not None else None,
                headers,
            )
            reply = connection.getresponse()
            metadata = route in {"key", "models"}
            if reply.status != 200:
                code = f"upstream_http_{reply.status}" if metadata else "upstream_unavailable"
                raise Denied(503, code)
            maximum = 65536 if route == "key" else MAX_REPLY
            raw = reply.read(maximum + 1)
            if len(raw) > maximum:
                raise Denied(503, "upstream_response_size" if metadata else "upstream_unavailable")
            result = json.loads(raw)
            # RouterAI key metadata also supports the documented one-element array wrapper.
            if not isinstance(result, dict) and not (route == "key" and isinstance(result, list)):
                raise ValueError
            return result
        except ssl.SSLError:
            raise Denied(
                503, "upstream_tls" if route in {"key", "models"} else "upstream_unavailable"
            ) from None
        except TimeoutError:
            raise Denied(
                503, "upstream_timeout" if route in {"key", "models"} else "upstream_unavailable"
            ) from None
        except (OSError, http.client.HTTPException):
            raise Denied(
                503, "upstream_network" if route in {"key", "models"} else "upstream_unavailable"
            ) from None
        except (ValueError, RecursionError):
            raise Denied(
                503,
                "upstream_invalid_json" if route in {"key", "models"} else "upstream_unavailable",
            ) from None
        finally:
            connection.close()

    def image_bytes(self, url):
        """Provider-supplied CDN URL only: public DNS pinned to prevent rebinding/SSRF."""
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise Denied(503, "invalid_image_url")
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise Denied(503, "invalid_image_url")
        connection = http.client.HTTPSConnection(parsed.hostname, timeout=60)
        raw_socket = socket.create_connection((addresses[0][4][0], 443), timeout=60)
        connection.sock = ssl.create_default_context().wrap_socket(
            raw_socket, server_hostname=parsed.hostname
        )
        try:
            # No RouterAI credential is sent to a CDN. No redirects are followed.
            connection.request(
                "GET", (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
            )
            response = connection.getresponse()
            raw = response.read(20 * 1024 * 1024 + 1)
            if response.status != 200 or len(raw) > 20 * 1024 * 1024:
                raise Denied(503, "image_unavailable")
            return raw
        finally:
            connection.close()


class Gateway:
    def __init__(self, store, upstream, text_model=TEXT_MODEL):
        if not re.fullmatch(r"deepseek/[A-Za-z0-9_.-]*flash[A-Za-z0-9_.-]*", text_model):
            raise ValueError("Only the owner-approved DeepSeek Flash model is allowed")
        self.store, self.upstream, self.text_model = store, upstream, text_model
        self.catalog_lock = threading.Lock()
        self._catalog = None
        self._catalog_at = 0

    def catalog(self):
        with self.catalog_lock:
            if self._catalog is None or time.monotonic() - self._catalog_at > 300:
                value = self.upstream.request("models")
                rows = value.get("data")
                if not isinstance(rows, list):
                    raise Denied(503, "catalog_unavailable")
                self._catalog = {
                    "data": [
                        r
                        for r in rows
                        if isinstance(r, dict) and r.get("id") in {self.text_model, RECRAFT, FLUX}
                    ]
                }
                self._catalog_at = time.monotonic()
            return self._catalog

    def validate(self, route, body, stage):
        if not isinstance(body, dict):
            raise Denied(400, "invalid_body")
        model = body.get("model")
        rows = [r for r in self.catalog()["data"] if r["id"] == model]
        if len(rows) != 1:
            raise Denied(400, "model_not_allowed")
        row = rows[0]
        if route == "chat/completions":
            if model != self.text_model or stage not in STAGES:
                raise Denied(400, "model_or_stage_not_allowed")
            if (
                set(body)
                - {
                    "model",
                    "messages",
                    "stream",
                    "max_tokens",
                    "max_completion_tokens",
                    "temperature",
                }
                or body.get("stream") is not False
            ):
                raise Denied(400, "parameters_not_allowed")
            messages = body.get("messages")
            if not isinstance(messages, list) or not 1 <= len(messages) <= 20:
                raise Denied(400, "messages")
            for message in messages:
                if (
                    not isinstance(message, dict)
                    or set(message) != {"role", "content"}
                    or message["role"] not in {"system", "user", "assistant"}
                    or not isinstance(message["content"], str)
                ):
                    raise Denied(400, "messages")
            incoming = sum(len(m["content"].encode()) + 8192 for m in messages)
            if incoming > min(int(row.get("context_length") or 0), 300000):
                raise Denied(413, "context_limit")
            if "max_tokens" in body and "max_completion_tokens" in body:
                raise Denied(400, "output_limit")
            output = body.get("max_tokens", body.get("max_completion_tokens"))
            if type(output) is not int or not 1 <= output <= (
                65536 if stage == "world_seed" else 16000
            ):
                raise Denied(400, "output_limit")
            if "temperature" in body and (
                type(body["temperature"]) not in (int, float) or not 0 <= body["temperature"] <= 2
            ):
                raise Denied(400, "temperature")
            pricing, units = row.get("pricing", {}), row.get("pricing_units", {})
            if units.get("prompt") != "token" or units.get("completion") != "token":
                raise Denied(503, "price_unavailable")
            price = micros(
                Decimal(str(pricing["prompt"])) * incoming
                + Decimal(str(pricing["completion"])) * output
            )
            return max(price, 1)
        if route != "images" or model not in IMAGE_CAPS or stage != "image":
            raise Denied(400, "model_or_stage_not_allowed")
        if (
            set(body)
            - {"model", "prompt", "n", "aspect_ratio", "resolution", "size", "input_references"}
            or body.get("n") != 1
            or type(body.get("n")) is not int
        ):
            raise Denied(400, "parameters_not_allowed")
        if not isinstance(body.get("prompt"), str) or not 1 <= len(body["prompt"]) <= 16000:
            raise Denied(400, "prompt")
        sizes = {
            "768": "768x768",
            "1K": "1024x1024",
            "1.5K": "1536x1536",
            "2K": "2048x2048",
            "4K": "4096x4096",
        }
        size = body.get("resolution", "1K")
        if "size" in body:
            matches = [k for k, v in sizes.items() if body["size"] == v]
            if len(matches) != 1 or "resolution" in body:
                raise Denied(400, "resolution")
            size = matches[0]
        if size not in sizes or size not in (row.get("supported_image_sizes") or ["1K"]):
            raise Denied(400, "resolution")
        if body.get("aspect_ratio", "1:1") not in {
            "1:1",
            "4:3",
            "3:4",
            "16:9",
            "9:16",
            "3:2",
            "2:3",
            "21:9",
            "auto",
        }:
            raise Denied(400, "aspect_ratio")
        refs = body.get("input_references", [])
        if not isinstance(refs, list) or len(refs) > min(row.get("max_image_references") or 0, 10):
            raise Denied(400, "references")
        if refs and (model != FLUX or row.get("supported_image_references") is not True):
            raise Denied(400, "references")
        for reference in refs:
            if (
                not isinstance(reference, dict)
                or set(reference) != {"type", "image_url"}
                or reference["type"] != "image_url"
            ):
                raise Denied(400, "references")
            url = reference["image_url"]
            if (
                not isinstance(url, dict)
                or set(url) != {"url"}
                or not isinstance(url["url"], str)
                or not url["url"].startswith("data:image/png;base64,")
            ):
                raise Denied(400, "references")
            raw = base64.b64decode(url["url"][22:], validate=True)
            if (
                len(raw) > 20 * 1024 * 1024
                or not raw.startswith(b"\x89PNG\r\n\x1a\n")
                or len(raw) < 24
            ):
                raise Denied(400, "references")
            width, height = int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
            if not 0 < width * height <= 16777216:
                raise Denied(400, "references")
        variants = row.get("image_pricing") or []
        exact = [
            r
            for r in variants
            if r.get("unit") == "image"
            and str(r.get("variant")).casefold() in {size.casefold(), sizes[size].casefold()}
        ]
        generic = [r for r in variants if r.get("unit") == "image" and r.get("variant") is None]
        choices = exact or generic
        if len(choices) != 1:
            raise Denied(503, "price_unavailable")
        price = micros(choices[0]["price"])
        for name, value in row.get("pricing", {}).items():
            if name == "image_output" or micros(value) == 0:
                continue
            if name == "request" and row.get("pricing_units", {}).get(name) == "request":
                price += micros(value)
            else:
                raise Denied(503, "price_unavailable")
        if not 0 < price <= IMAGE_CAPS[model]:
            raise Denied(429, "image_price_limit")
        return price

    def handle(self, route, token, body=None, identity="", stage=""):
        self.store.identity(token)
        if route == "key" and body is None:
            return self.store.allowance(token)
        if route == "models" and body is None:
            return self.catalog()
        try:
            expected = self.validate(route, body, stage)
        except (ValueError, TypeError, KeyError, ArithmeticError):
            raise Denied(400, "invalid_or_unpriced_request") from None
        user = self.store.reserve(token, identity, expected, stage)
        return self.execute(route, body, user, identity)

    def execute(self, route, body, user, identity):
        actual, succeeded = None, False
        try:
            result = self.upstream.request(route, body)
            usage = result.get("usage") or {}
            cost = result.get("cost_rub", usage.get("cost_rub"))
            if cost is None and route == "images" and usage.get("currency", "RUB") == "RUB":
                cost = usage.get("cost")
            if cost is not None:
                actual = micros(cost)
            if route == "images":
                data = result.get("data")
                if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
                    raise Denied(503, "image_unavailable")
                if "url" in data[0]:
                    raw = self.upstream.image_bytes(data[0]["url"])
                    data = [{"b64_json": base64.b64encode(raw).decode()}]
                result = {
                    "data": data,
                    "usage": {"cost_rub": actual / 1e6} if actual is not None else {},
                }
            else:
                # Drop unknown provider metadata which could contain internal diagnostics.
                result = {k: result[k] for k in ("choices", "model", "usage") if k in result}
            succeeded = True
            return result
        finally:
            self.store.settle(user, identity, actual, succeeded=succeeded)


class Handler(BaseHTTPRequestHandler):
    server_version = "DNDGateway"

    def log_message(self, *args):
        pass  # No URLs, authorization headers, prompts or user messages in access logs.

    def do_GET(self):
        self.process(False)

    def do_POST(self):
        self.process(True)

    def process(self, post):
        if not self.server.slots.acquire(blocking=False):
            self.respond(503, {"error": {"code": "busy"}})
            return
        try:
            self.connection.settimeout(20)
            routes = {
                "/api/v1/models": "models",
                "/api/v1/key": "key",
                "/api/v1/chat/completions": "chat/completions",
                "/api/v1/images": "images",
            }
            if self.path == "/api/v1/health" and not post:
                self.respond(200, {"service": "dnd-gateway", "protocol": 1, "async_jobs": True})
                return
            if self.path == "/api/v1/activate" and post:
                if self.headers.get_content_type() != "application/json" or self.headers.get(
                    "Transfer-Encoding"
                ):
                    raise Denied(400, "content_type")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024:
                    raise Denied(413, "request_size")
                value = json.loads(self.rfile.read(length))
                self.respond(
                    200,
                    self.server.gateway.store.activate(
                        value.get("code"), value.get("installation")
                    ),
                )
                return
            route = routes.get(self.path)
            if not post and re.fullmatch(r"/api/v1/jobs/[a-f0-9]{32}", self.path):
                route = "job"
            if route is None or post != (route in {"chat/completions", "images"}):
                raise Denied(404, "route_not_found")
            authorization = self.headers.get("Authorization", "")
            token = authorization[7:] if authorization.startswith("Bearer ") else ""
            self.server.gateway.store.identity(token)  # Authenticate before reading a large body.
            if route == "job":
                status, value = self.server.jobs.get(token, self.path.rsplit("/", 1)[1])
                self.respond(status, value)
                return
            body = None
            if post:
                if (
                    self.headers.get("Transfer-Encoding")
                    or self.headers.get_content_type() != "application/json"
                ):
                    raise Denied(400, "content_type")
                length = int(self.headers.get("Content-Length", "0"))
                maximum = 250000 if route == "chat/completions" else MAX_BODY
                if not 0 < length <= maximum:
                    raise Denied(413, "request_size")
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise Denied(400, "incomplete_body")
                body = json.loads(raw)
            if post and self.headers.get("Prefer") == "respond-async":
                status, value = self.server.jobs.submit(
                    route,
                    token,
                    body,
                    self.headers.get("X-Request-ID", ""),
                    self.headers.get("X-DND-Stage", ""),
                )
                self.respond(status, value)
                return
            value = self.server.gateway.handle(
                route,
                token,
                body,
                self.headers.get("X-Request-ID", ""),
                self.headers.get("X-DND-Stage", ""),
            )
            self.respond(200, value)
        except Denied as error:
            self.respond(error.status, {"error": {"code": error.code}})
        except (ValueError, TypeError, RecursionError, ArithmeticError):
            self.respond(400, {"error": {"code": "invalid_request"}})
        except Exception:
            self.respond(503, {"error": {"code": "service_unavailable"}})
        finally:
            self.server.slots.release()

    def respond(self, status, value):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (OSError, ConnectionError):
            pass
        self.close_connection = True


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, gateway):
        super().__init__(address, Handler)
        self.gateway = gateway
        from server.jobs import Jobs

        self.jobs = Jobs(gateway)
        self.slots = threading.BoundedSemaphore(16)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("gateway-data/access.sqlite3"))
    parser.add_argument("--global-rub", type=int, default=100)
    commands = parser.add_subparsers(dest="command", required=True)
    issue = commands.add_parser("issue")
    issue.add_argument("id")
    issue.add_argument("--rub", type=int, default=10)
    issue.add_argument("--days", type=int, default=7)
    issue.add_argument("--requests", type=int, default=50)
    issue.add_argument("--worlds", type=int, default=2)
    revoke = commands.add_parser("revoke")
    revoke.add_argument("id")
    extend = commands.add_parser("extend")
    extend.add_argument("id")
    extend.add_argument("--days", type=int, required=True)
    commands.add_parser("list")
    serve = commands.add_parser("serve")
    serve.add_argument("--bind", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8443)
    serve.add_argument("--cert")
    serve.add_argument("--key")
    serve.add_argument("--local-http", action="store_true")
    serve.add_argument("--text-model", default=TEXT_MODEL)
    args = parser.parse_args()
    store = Store(args.db, args.global_rub * 1000000)
    if args.command == "issue":
        print(
            store.issue(
                args.id,
                days=args.days,
                budget=args.rub * 1000000,
                requests=args.requests,
                worlds=args.worlds,
            )
        )
    elif args.command == "revoke":
        store.revoke(args.id)
    elif args.command == "extend":
        store.extend(args.id, args.days)
    elif args.command == "list":
        print(json.dumps(store.summary(), indent=2))
    else:
        if args.local_http and args.bind != "127.0.0.1":
            parser.error("--local-http requires --bind 127.0.0.1")
        if not args.local_http and not (args.cert and args.key):
            parser.error("TLS certificate required (or explicit loopback --local-http)")
        gateway = Gateway(store, Upstream(os.environ.get("DND_ROUTERAI_KEY", "")), args.text_model)
        server = Server((args.bind, args.port), gateway)
        if not args.local_http:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(args.cert, args.key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
        print("Gateway listening; no prompt or token logs.")
        server.serve_forever()


if __name__ == "__main__":
    main()
