"""In-memory request routing without Profile or page-content caching."""

from __future__ import annotations

import queue
import threading
from typing import Any


class PendingRequests:
    def __init__(self) -> None:
        self._items: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def create(self, request_id: str) -> queue.Queue[dict[str, Any]] | None:
        waiter: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._lock:
            if request_id in self._items:
                return None
            self._items[request_id] = waiter
        return waiter

    def deliver(self, request_id: str, response: dict[str, Any]) -> bool:
        with self._lock:
            waiter = self._items.get(request_id)
        if waiter is None:
            return False
        waiter.put(response)
        return True

    def remove(self, request_id: str) -> None:
        with self._lock:
            self._items.pop(request_id, None)
