"""Small in-process SSE broadcaster for the local single-user shell."""

import asyncio
from collections import deque
from collections.abc import AsyncIterator


class EventBroadcaster:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict]] = set()
        self._trace_request_id: str | None = None
        self._trace_events: list[dict] = []
        self._trace_maintenance: dict | None = None
        self._retired_trace_ids: deque[str] = deque(maxlen=20)

    async def publish(self, event: dict) -> None:
        self.publish_nowait(event)

    def action_trace_snapshot(self) -> dict:
        """Bounded replay of the latest request, including an in-flight request."""
        return {"request_id": self._trace_request_id, "events": list(self._trace_events),
                "maintenance": self._trace_maintenance}

    def publish_nowait(self, event: dict) -> None:
        if event.get("type") == "agent_event":
            item = event.get("event", {})
            request_id = item.get("request_id")
            if request_id and request_id != self._trace_request_id and request_id not in self._retired_trace_ids and (
                    self._trace_request_id is None or item.get("event_type") in {"runtime_started", "request_started"}):
                if self._trace_request_id:
                    self._retired_trace_ids.append(self._trace_request_id)
                self._trace_request_id = request_id
                self._trace_events = []
                self._trace_maintenance = None
            if request_id and request_id == self._trace_request_id:
                self._trace_events.append(item)
                # Keep the first event plus the latest 299, even on long requests.
                if len(self._trace_events) > 300:
                    del self._trace_events[1]
        elif event.get("type") == "maintenance_status" and self._trace_request_id and event.get("request_id") == self._trace_request_id:
            self._trace_maintenance = event
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    async def subscribe(self) -> AsyncIterator[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

