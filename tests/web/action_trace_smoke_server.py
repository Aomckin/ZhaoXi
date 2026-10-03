"""Isolated delayed fake-agent server for real SSE trace acceptance."""
import asyncio
from pathlib import Path
import uvicorn
from dashboard_fixture import dashboard_core
from zhaoxi.observability import current_trace
from zhaoxi.web.app import create_app

if __name__ == "__main__":
    path = Path(".zhaoxi/action-trace-fixture")
    path.mkdir(parents=True, exist_ok=True)
    core, settings = dashboard_core(path)
    settings.dev_browser_ui = False
    core.internal_activity.control.update("presence", {"heartbeat_enabled": False})
    original = core.run_natural

    async def delayed_reply(message):
        trace = current_trace()
        trace.emit("model_step_started", "model", "running", "隔离模型正在处理")
        await asyncio.sleep(4)
        trace.emit("model_step_finished", "model", "success", "隔离模型处理完成")
        return await original(message)

    core.run_natural = delayed_reply
    uvicorn.run(create_app(agent=core, settings=settings, api_token="dashboard-ui-test"),
                host="127.0.0.1", port=18765)
