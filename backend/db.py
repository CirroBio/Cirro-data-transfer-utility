"""SQLite persistence: manifest cache + transfer queue + per-dataset state.

Everything the app needs to resume after a restart lives here. A fresh
connection is opened per operation (cheap for a local single-user app) with
WAL enabled so the background worker and the API can read/write concurrently.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from backend.config import config

# Serialize writes across threads; WAL lets readers proceed in parallel.
_write_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    name         TEXT PRIMARY KEY,
    project      TEXT,
    data_type    TEXT NOT NULL,
    description  TEXT DEFAULT '',
    folder_path  TEXT,
    tags_json    TEXT DEFAULT '[]',
    status       TEXT NOT NULL DEFAULT 'PENDING',
    error        TEXT,
    dataset_id   TEXT,
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS files (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_name      TEXT NOT NULL,
    source_uri        TEXT NOT NULL,
    relative_path     TEXT NOT NULL,
    expected_size     INTEGER,
    expected_checksum TEXT,
    checksum_type     TEXT,
    verify_tier       TEXT,
    status            TEXT NOT NULL DEFAULT 'PENDING',
    downloaded_bytes  INTEGER NOT NULL DEFAULT 0,
    error             TEXT,
    UNIQUE (dataset_name, relative_path)
);

CREATE TABLE IF NOT EXISTS manifest_cache (
    project_id  TEXT NOT NULL,
    name        TEXT NOT NULL,
    dataset_id  TEXT,
    files_json  TEXT NOT NULL,
    cached_at   TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (project_id, name)
);

CREATE TABLE IF NOT EXISTS queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_name TEXT NOT NULL UNIQUE,
    state        TEXT NOT NULL DEFAULT 'QUEUED',
    enqueued_at  TEXT DEFAULT (datetime('now'))
);
"""


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or config.db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def read() -> Iterator[sqlite3.Connection]:
    """Read-only connection (no lock)."""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def write() -> Iterator[sqlite3.Connection]:
    """Write connection guarded by the module lock; commits on clean exit."""
    with _write_lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
