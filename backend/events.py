"""Tiny in-process pub/sub used to push progress to the event endpoints.

The background worker (a plain thread) publishes dict events. SSE clients each
hold a ``queue.Queue`` they drain; polling clients instead read a shared ring
buffer of recent events by sequence number, so they need no server-side state.
Thread-safe and dependency-free.
"""
from __future__ import annotations

import queue
import threading
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

# How many recent events a polling client can miss and still catch up. Byte
# progress is throttled to one event per 0.25s per file, so this is on the order
# of minutes of history — far more than the ~1s poll interval needs.
RECENT_EVENTS = 500


class Broker:
    def __init__(self) -> None:
        self._subscribers: List[queue.Queue] = []
        self._lock = threading.Lock()
        self._seq = 0
        self._recent: Deque[Tuple[int, Dict]] = deque(maxlen=RECENT_EVENTS)

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
            self._seq += 1
            self._recent.append((self._seq, event))
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # slow client — drop rather than block the worker

    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq

    def since(self, cursor: Optional[int]) -> Dict:
        """Events published after ``cursor``, for clients that poll.

        A client with no cursor starts from now: replaying buffered progress for
        a transfer that has since finished would leave stale bars on screen. A
        cursor older than the buffer reports ``gap``, telling the client to
        resync from the REST endpoints rather than apply a partial stream.
        """
        with self._lock:
            if cursor is None:
                return {"seq": self._seq, "events": [], "gap": False}
            if self._recent and cursor < self._recent[0][0] - 1:
                return {"seq": self._seq, "events": [], "gap": True}
            events = [event for seq, event in self._recent if seq > cursor]
        return {"seq": self._seq, "events": events, "gap": False}


broker = Broker()
