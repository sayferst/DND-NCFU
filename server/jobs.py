"""Bounded private result cache: HTTP polling never repeats a generation."""

import json
import threading
import time
import uuid
from contextlib import closing

from server.gateway import Denied


class Jobs:
    def __init__(self, gateway, *, ttl=1800, capacity=16, clock=time.monotonic):
        self.gateway, self.ttl, self.capacity, self.clock = gateway, ttl, capacity, clock
        self.lock = threading.Lock()
        self.rows = {}

    def submit(self, route, token, body, request_id, stage):
        user = self.gateway.store.identity(token)["id"]
        with self.lock:
            now = self.clock()
            self.rows = {
                k: r
                for k, r in self.rows.items()
                if r["status"] == 202 or now - r["updated"] < self.ttl
            }
            for key, row in self.rows.items():
                if row["user"] == user and row["request_id"] == request_id:
                    return 202, {"job": key}
            with closing(self.gateway.store.connect()) as db:
                if db.execute(
                    "SELECT 1 FROM calls WHERE tester=? AND id=?", (user, request_id)
                ).fetchone():
                    raise Denied(409, "request_already_received")
            # Includes completed results (images can be large); bounded total cache.
            # Evict completed results under memory/slot pressure, never pending work.
            while (
                len(self.rows) >= self.capacity
                or sum(len(json.dumps(r["value"])) for r in self.rows.values()) > 64 * 1024 * 1024
            ):
                completed = [(r["updated"], k) for k, r in self.rows.items() if r["status"] != 202]
                if not completed:
                    raise Denied(503, "job_capacity")
                self.rows.pop(min(completed)[1])
            try:
                expected = self.gateway.validate(route, body, stage)
            except (ValueError, TypeError, KeyError, ArithmeticError):
                raise Denied(400, "invalid_or_unpriced_request") from None
            self.gateway.store.reserve(token, request_id, expected, stage)
            key = uuid.uuid4().hex
            row = {
                "user": user,
                "request_id": request_id,
                "status": 202,
                "value": {"job": key},
                "updated": now,
            }
            self.rows[key] = row

            def run():
                try:
                    value = self.gateway.execute(route, body, user, request_id)
                    status = 200
                except Denied as error:
                    status, value = error.status, {"error": {"code": error.code}}
                except Exception:
                    status, value = 503, {"error": {"code": "generation_failed"}}
                with self.lock:
                    row.update(status=status, value=value, updated=self.clock())

            threading.Thread(target=run, daemon=True).start()
            return 202, {"job": key}

    def get(self, token, key):
        user = self.gateway.store.identity(token)["id"]
        with self.lock:
            row = self.rows.get(key)
            if (
                row is None
                or row["user"] != user
                or (row["status"] != 202 and self.clock() - row["updated"] >= self.ttl)
            ):
                raise Denied(404, "job_unavailable")
            return row["status"], row["value"]
