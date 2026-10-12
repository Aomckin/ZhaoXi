"""Isolated delayed fake-agent server for real SSE trace acceptance."""
import asyncio
import os
from pathlib import Path
import uvicorn
from dashboard_fixture import dashboard_core
from zhaoxi.observability import current_trace
from zhaoxi.models.resilient import ResilientProvider
from zhaoxi.models.types import ModelResponse
from zhaoxi.web.app import create_app

if __name__ == "__main__":
    path = Path(".pytest_cache/action-records-browser-fixture")
    path.mkdir(parents=True, exist_ok=True)
    core, settings = dashboard_core(path)
    settings.dev_browser_ui = False
    core.internal_activity.control.update("presence", {"heartbeat_enabled": False})
    original = core.run_natural

    async def delayed_reply(message):
        trace = current_trace()
        class SyntheticProvider:
            model = "synthetic-action-model"
            calls = 0

            async def generate(self, *args, **kwargs):
                self.calls += 1
                return (ModelResponse(content="我会先核对资料，再汇总结果。", usage={"prompt_tokens": 1200, "completion_tokens": 80})
                        if self.calls == 1 else
                        ModelResponse(content="你好，暗苟酱。", usage={"prompt_tokens": 1600, "completion_tokens": 120}))

        provider = ResilientProvider([SyntheticProvider()])
        trace.emit("model_step_started", "model", "running", "隔离模型正在处理")
        await provider.generate([])
        await asyncio.sleep(4)
        final = await provider.generate([])
        trace.mark_final_reply(final)
        trace.emit("model_step_finished", "model", "success", "隔离模型处理完成")
        return await original(message)

    core.run_natural = delayed_reply
    uvicorn.run(create_app(agent=core, settings=settings, api_token="dashboard-ui-test"),
                host="127.0.0.1", port=int(os.environ.get("ZHAOXI_TEST_PORT", "18765")))
