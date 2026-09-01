import asyncio

import pytest

from zhaoxi.reliability.lifecycle import TaskSupervisor


@pytest.mark.asyncio
async def test_supervisor_completes_fast_tasks_and_cancels_stuck_tasks():
    supervisor = TaskSupervisor()
    completed = asyncio.Event()

    async def fast():
        completed.set()

    async def stuck():
        await asyncio.Event().wait()

    supervisor.create(fast(), name="fast")
    supervisor.create(stuck(), name="stuck")
    await completed.wait()
    result = await supervisor.shutdown(0)
    assert result["cancelled"] == 1
    assert supervisor.active_count == 0


@pytest.mark.asyncio
async def test_supervisor_rejects_tasks_after_shutdown():
    supervisor = TaskSupervisor()
    await supervisor.shutdown(0)
    with pytest.raises(RuntimeError, match="关闭"):
        supervisor.create(asyncio.sleep(0), name="late")
