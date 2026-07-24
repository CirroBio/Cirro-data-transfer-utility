"""Manifest cache: Cirro dataset file-lists keyed by (project_id, dataset_key).

A dataset's file list is treated as stable once it exists, so reconcile can
avoid re-querying Cirro. The cache is invalidated for a dataset when we upload
it (its manifest changes from "absent" to "present"). Keyed by dataset_key (not
name) because a name can recur across folders within one project.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from backend import db


def get(project_id: str, dataset_key: str) -> Optional[Dict]:
    with db.read() as conn:
        row = conn.execute(
            "SELECT dataset_id, files_json FROM manifest_cache "
            "WHERE project_id=? AND dataset_key=?",
            (project_id, dataset_key),
        ).fetchone()
    if row is None:
        return None
    return {"dataset_id": row["dataset_id"], "files": json.loads(row["files_json"])}


def put(project_id: str, dataset_key: str, dataset_id: Optional[str], files: List[Dict]) -> None:
    with db.write() as conn:
        conn.execute(
            """
            INSERT INTO manifest_cache (project_id, dataset_key, dataset_id, files_json, cached_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(project_id, dataset_key) DO UPDATE SET
                dataset_id=excluded.dataset_id,
                files_json=excluded.files_json,
                cached_at=excluded.cached_at
            """,
            (project_id, dataset_key, dataset_id, json.dumps(files)),
        )


def invalidate(project_id: str, dataset_key: str) -> None:
    with db.write() as conn:
        conn.execute(
            "DELETE FROM manifest_cache WHERE project_id=? AND dataset_key=?",
            (project_id, dataset_key),
        )
