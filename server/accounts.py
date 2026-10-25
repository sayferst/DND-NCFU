"""Server-only password verifiers and revocable sessions; no provider keys in clients."""

import hashlib
import hmac
import secrets
from contextlib import closing

from server.gateway import Denied, digest


def initialize(store):
    with closing(store.connect()) as db, db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS accounts(
                name TEXT PRIMARY KEY, tester TEXT UNIQUE NOT NULL,
                salt TEXT NOT NULL, verifier TEXT NOT NULL,
                failures INTEGER NOT NULL DEFAULT 0, blocked REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS sessions(
                hash TEXT PRIMARY KEY, tester TEXT NOT NULL, expires REAL NOT NULL);
        """)


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600000).hex()


def configure(store, name, password):
    if (
        name not in {"admin", "tester"}
        or not isinstance(password, str)
        or not 4 <= len(password) <= 128
    ):
        raise ValueError("Account/password format")
    initialize(store)
    identity = "account_" + name
    budget = 500_000_000 if name == "admin" else 100_000_000
    with closing(store.connect()) as db:
        exists = db.execute("SELECT 1 FROM testers WHERE id=?", (identity,)).fetchone()
    if not exists:
        store.issue(identity, days=30, budget=budget, requests=10000, worlds=100)
    salt = secrets.token_hex(24)
    with closing(store.connect()) as db, db:
        db.execute(
            "INSERT INTO accounts(name,tester,salt,verifier) VALUES(?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET salt=excluded.salt,verifier=excluded.verifier,"
            "failures=0,blocked=0",
            (name, identity, salt, password_hash(password, salt)),
        )
        db.execute("DELETE FROM sessions WHERE tester=?", (identity,))


def login(store, name, password):
    if not isinstance(name, str) or not isinstance(password, str) or len(password) > 128:
        raise Denied(401, "login_failed")
    initialize(store)
    denied = None
    token = secrets.token_urlsafe(32)
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM accounts WHERE name=?", (name,)).fetchone()
        now = store.clock()
        if row and row["blocked"] > now:
            raise Denied(429, "login_throttled")
        salt = row["salt"] if row else "00" * 24
        candidate = password_hash(password, salt)
        if not row or not hmac.compare_digest(candidate, row["verifier"]):
            if row:
                failures = row["failures"] + 1
                db.execute(
                    "UPDATE accounts SET failures=?,blocked=? WHERE name=?",
                    (0 if failures >= 5 else failures, now + 60 if failures >= 5 else 0, name),
                )
            denied = Denied(401, "login_failed")
        else:
            user = db.execute("SELECT * FROM testers WHERE id=?", (row["tester"],)).fetchone()
            if not user or user["revoked"] or user["expires"] <= now:
                raise Denied(401, "access_expired_or_revoked")
            db.execute("UPDATE accounts SET failures=0,blocked=0 WHERE name=?", (name,))
            db.execute("DELETE FROM sessions WHERE expires<=?", (now,))
            # Keep only the four most recent logins per account; one password is one budget.
            db.execute(
                "DELETE FROM sessions WHERE tester=? AND hash NOT IN "
                "(SELECT hash FROM sessions WHERE tester=? ORDER BY rowid DESC LIMIT 3)",
                (row["tester"], row["tester"]),
            )
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?)",
                (digest(token), row["tester"], min(user["expires"], now + 86400)),
            )
    if denied:
        raise denied
    return {"token": token, "account": name, "budget_rub": user["budget"] / 1e6}
