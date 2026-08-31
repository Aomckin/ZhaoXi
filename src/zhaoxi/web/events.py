"""Small in-process SSE broadcaster for the local single-user shell."""

import asyncio
from collections.abc import AsyncIterator


class EventBroadcaster:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict]] = set()

    async def publish(self, event: dict) -> None:
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

