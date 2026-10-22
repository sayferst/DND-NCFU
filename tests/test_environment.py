"""Integration checks of the development environment, not tests of a game."""

import sqlite3
import sys

import pytest


def test_python_is_supported_and_isolated():
    assert sys.version_info[:2] == (3, 12), "Use Python 3.12"
    assert sys.prefix != sys.base_prefix, "Run pytest using .venv Python"


def test_sqlite_persists_unicode_after_reopening(tmp_path):
    database = tmp_path / "проверка.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE notes (body TEXT NOT NULL)")
        with connection:
            connection.execute("INSERT INTO notes VALUES (?)", ("Запись исследования",))
    finally:
        connection.close()
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT body FROM notes").fetchall() == [("Запись исследования",)]
    finally:
        connection.close()


def test_sqlite_rolls_back_failed_transaction(tmp_path):
    connection = sqlite3.connect(tmp_path / "transaction.sqlite3")
    try:
        connection.execute("CREATE TABLE samples (id INTEGER PRIMARY KEY, value INTEGER NOT NULL)")
        with connection:
            connection.execute("INSERT INTO samples VALUES (1, 10)")
        with pytest.raises(sqlite3.IntegrityError), connection:
            connection.execute("UPDATE samples SET value = 20 WHERE id = 1")
            connection.execute("INSERT INTO samples VALUES (1, 30)")
        assert connection.execute("SELECT id, value FROM samples").fetchall() == [(1, 10)]
    finally:
        connection.close()
