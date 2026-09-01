"""Bounded background-task supervision and graceful shutdown."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine


class TaskSupervisor:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()
        self.accepting = True

    def create(self, coroutine: Coroutine, *, name: str) -> asyncio.Task:
        if not self.accepting:
            coroutine.close()
            raise RuntimeError("运行时正在关闭，不再接受后台任务。")
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def start(self) -> None:
        if self.active_count:
            raise RuntimeError("仍有后台任务运行，不能重新启动 supervisor。")
        self.accepting = True

    async def shutdown(self, grace_seconds: float, *, cancel_immediately: bool = False) -> dict[str, int]:
        self.accepting = False
        tasks = {task for task in self._tasks if not task.done()}
        if not tasks:
            return {"completed": 0, "cancelled": 0}
        if cancel_immediately:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            return {"completed": 0, "cancelled": len(tasks)}
        done, pending = await asyncio.wait(tasks, timeout=grace_seconds)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return {"completed": len(done), "cancelled": len(pending)}

    @property
    def active_count(self) -> int:
        return sum(not task.done() for task in self._tasks)
