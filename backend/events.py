"""Tiny in-process pub/sub used to push progress to the SSE endpoint.

The background worker (a plain thread) publishes dict events; each SSE client
holds a ``queue.Queue`` it drains. Thread-safe and dependency-free.
"""
from __future__ import annotations

import queue
import threading
from typing import Dict, List


class Broker:
    def __init__(self) -> None:
        self._subscribers: List[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, event: Dict) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # slow client — drop rather than block the worker


broker = Broker()
