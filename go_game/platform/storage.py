"""Durable single-host SQLite WAL and transaction boundary.

No SQLite database on NFS/multi-host; scale-out requires Postgres + object store.
"""
import json
import os
import sqlite3
from contextlib import contextmanager


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, ensure_ascii=True)


class PlatformStore:
    def __init__(self, path):
        if str(path) == ":memory:":
            raise ValueError("Use a real SQLite file; one connection per transaction")
        self.path = os.path.abspath(os.fspath(path))
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS games (
                    id TEXT PRIMARY KEY,
                    rules TEXT NOT NULL, black_actor TEXT NOT NULL,
                    white_actor TEXT NOT NULL, model_id TEXT NOT NULL,
                    seq INTEGER NOT NULL DEFAULT 0,
                    state_hash TEXT NOT NULL, terminated INTEGER NOT NULL DEFAULT 0,
                    created_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS game_events (
                    game_id TEXT NOT NULL REFERENCES games(id),
                    seq INTEGER NOT NULL, command_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL, event TEXT NOT NULL,
                    response TEXT NOT NULL,
                    PRIMARY KEY(game_id, seq), UNIQUE(game_id, command_id)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL,
                    request_key TEXT NOT NULL, spec_hash TEXT NOT NULL,
                    spec TEXT NOT NULL, status TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT, lease_until REAL,
                    artifact_digest TEXT, created_utc TEXT NOT NULL,
                    updated_utc TEXT NOT NULL,
                    UNIQUE(owner, request_key)
                );
                CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status, created_utc);
            """)

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def connection(self):
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def write(self):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
