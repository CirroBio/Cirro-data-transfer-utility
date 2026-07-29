"""SQLite persistence: the loaded plan, the transfer queue, and per-dataset state.

Everything the app needs to resume after a restart lives here. A fresh
connection is opened per operation (cheap for a local single-user app) with
WAL enabled so the background worker and the API can read/write concurrently.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Optional

from backend.config import config

# Serialize writes across threads; WAL lets readers proceed in parallel.
_write_lock = threading.Lock()

# A dataset's identity is (name, folder_path); `key` folds that pair into one
# string (see schema.dataset_key) and is the join used by files/queue/cache.
SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    key             TEXT PRIMARY KEY,
    name            TEXT NOT NULL,          -- target_dataset_name (Cirro name)
    study           TEXT NOT NULL,          -- the Cirro project
    folder_path     TEXT NOT NULL,          -- cirro_folder_path (rooted at study)
    data_type       TEXT NOT NULL DEFAULT '', -- cirro_type_id (ingest process)
    cirro_type_name TEXT DEFAULT '',
    source_kind     TEXT,
    source_dataset_id TEXT,
    source_subpath  TEXT,
    planned_files   INTEGER,
    planned_bytes   INTEGER,
    description     TEXT DEFAULT '',
    tags_json       TEXT DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'PENDING',
    error           TEXT,
    dataset_id      TEXT,
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS excluded_datasets (
    study             TEXT NOT NULL,
    source_dataset_id TEXT NOT NULL,
    source_kind       TEXT,
    source_subpath    TEXT,
    n_files           INTEGER,
    total_size_bytes  INTEGER,
    excluded_at       TEXT,
    PRIMARY KEY (study, source_dataset_id)
);

CREATE TABLE IF NOT EXISTS files (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_key       TEXT NOT NULL,
    source_uri        TEXT NOT NULL,          -- source_location
    relative_path     TEXT NOT NULL,          -- target_relative_path
    expected_size     INTEGER,
    expected_checksum TEXT,                    -- file_plan.hash
    checksum_type     TEXT,
    checksum_encoding TEXT NOT NULL DEFAULT 'hex',
    source_dataset_id TEXT,
    source_subpath    TEXT,
    source_pathname   TEXT,
    verify_tier       TEXT,
    status            TEXT NOT NULL DEFAULT 'PENDING',
    downloaded_bytes  INTEGER NOT NULL DEFAULT 0,
    error             TEXT,
    UNIQUE (dataset_key, relative_path)
);

CREATE TABLE IF NOT EXISTS queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_key  TEXT NOT NULL UNIQUE,
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


def clear_plan() -> Dict[str, int]:
    """Drop the loaded plan and everything derived from it, returning the row
    counts removed. Local state only — datasets already in Cirro are untouched.
    """
    tables = ["files", "datasets", "excluded_datasets", "queue"]
    removed: Dict[str, int] = {}
    with write() as conn:
        for table in tables:
            removed[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            conn.execute(f"DELETE FROM {table}")
    return removed


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
