"""Durable transfer queue backed by the SQLite ``queue`` table.

A small pool of worker threads (size = config.concurrency, default 1) claims
queued datasets atomically and runs them through ``transfer_dataset``. Because
the queue lives in SQLite, a restart resumes cleanly: in-flight items are
re-queued and interrupted uploads resume via the transfer state machine.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional

from backend import db
from backend.cirro_gateway import CirroGateway, gateway as default_gateway
from backend.events import broker
from backend.models import Status
from backend.transfer import transfer_dataset


class TransferQueue:
    def __init__(self, gateway: CirroGateway = default_gateway, concurrency: int = 1):
        self.gateway = gateway
        self.concurrency = max(1, concurrency)
        self.default_project: Optional[str] = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []

    # ---- lifecycle ------------------------------------------------------

    def start(self) -> None:
        self.recover()
        for i in range(self.concurrency):
            t = threading.Thread(target=self._loop, name=f"transfer-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def recover(self) -> None:
        """After a restart, move any RUNNING queue rows back to QUEUED and reset
        datasets left mid-flight so they get re-processed."""
        with db.write() as conn:
            conn.execute("UPDATE queue SET state='QUEUED' WHERE state='RUNNING'")
            conn.execute(
                f"""UPDATE datasets SET status='{Status.FAILED}',
                    error='Interrupted by restart; will resume'
                    WHERE status IN ({','.join('?' * len(Status.IN_FLIGHT))})""",
                tuple(Status.IN_FLIGHT),
            )
        self._wake.set()

    # ---- enqueue --------------------------------------------------------

    def enqueue(self, keys: List[str]) -> List[str]:
        queued = []
        with db.write() as conn:
            for key in keys:
                exists = conn.execute(
                    "SELECT 1 FROM datasets WHERE key=?", (key,)
                ).fetchone()
                if not exists:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO queue (dataset_key, state) VALUES (?, 'QUEUED')",
                    (key,),
                )
                conn.execute(
                    "UPDATE datasets SET status=? WHERE key=? AND status NOT IN (?, ?)",
                    (Status.PENDING, key, Status.DONE, Status.PRESENT),
                )
                queued.append(key)
        self._wake.set()
        broker.publish({"type": "queue", "action": "enqueued", "keys": queued})
        return queued

    def snapshot(self) -> List[Dict]:
        with db.read() as conn:
            rows = conn.execute(
                "SELECT q.dataset_key, d.name, q.state, q.enqueued_at FROM queue q "
                "LEFT JOIN datasets d ON d.key = q.dataset_key ORDER BY q.id"
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- worker ---------------------------------------------------------

    def _claim_next(self) -> Optional[str]:
        with db.write() as conn:
            row = conn.execute(
                "SELECT id, dataset_key FROM queue WHERE state='QUEUED' ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE queue SET state='RUNNING' WHERE id=?", (row["id"],))
            return row["dataset_key"]

    def _finish(self, key: str) -> None:
        with db.write() as conn:
            conn.execute("DELETE FROM queue WHERE dataset_key=?", (key,))

    def _loop(self) -> None:
        while not self._stop.is_set():
            key = self._claim_next()
            if key is None:
                self._wake.wait(timeout=2.0)
                self._wake.clear()
                continue
            if not self.gateway.connected:
                # Can't transfer without Cirro; put it back and wait.
                with db.write() as conn:
                    conn.execute("UPDATE queue SET state='QUEUED' WHERE dataset_key=?", (key,))
                self._wake.wait(timeout=2.0)
                continue
            try:
                transfer_dataset(self.gateway, key, self.default_project, broker.publish)
            finally:
                self._finish(key)
