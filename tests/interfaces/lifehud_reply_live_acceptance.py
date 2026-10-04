"""Explicit live-model smoke test; synthetic dialogue and MockTransport only.

Run manually from the repository root. Never starts a production LifeHUD timer.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tests/interfaces")]
from test_tool_reply_recovery import setup
from zhaoxi.bootstrap.models import build_model_runtime
from zhaoxi.config.settings import Settings
from zhaoxi.interfaces import UnifiedMessage
from zhaoxi.models.base import ModelProvider
from zhaoxi.models.types import ModelResponse


async def main():
    settings = Settings()
    settings.retry_max_attempts = 1
    actual = build_model_runtime(settings)
    core, fixture_provider, gateway, requests = setup([])
    rows, injected = [], False

    class Capture(ModelProvider):
        async def generate(self, messages, tools=None, **kwargs):
            nonlocal injected
            # Seed the already-successful operation with the fixture native
            # call; the two post-tool replies use the real configured model.
            source = "fixture_tool_call" if not rows else "configured_model"
            result = (fixture_provider.responses[0] if not rows else
                      await actual.generate(messages, tools, **kwargs))
            row = {"source": source, "tool_names": [call.name for call in result.tool_calls],
                   "content_chars": len(result.content or ""), "tools_exposed": bool(tools),
                   "finish_reason": result.finish_reason, "usage": result.usage}
            # Deliberately simulate the observed 81-space final response once.
            if len(rows) == 1 and not injected:
                injected = True
                result = result.model_copy(update={"content": " " * 81, "tool_calls": [], "finish_reason": "stop"})
                row["injected_blank"] = True
            rows.append(row)
            return result

    core.provider = Capture()
    start = time.perf_counter()
    result = await gateway.chat(UnifiedMessage(channel="web", request_id="synthetic-focus-recovery",
        content="请在 LifeHUD 开一个25分钟番茄钟，标题为合成验收：整理示例代码。"))
    body = {"passed": True, "synthetic_only": True, "lifehud_transport": "httpx.MockTransport", "operation_selection": "fixture native call",
            "injected_blank": injected, "reply": result.content, "response_status": core.last_action_trace["response_status"],
            "provider_calls": rows, "local_http_calls": requests,
            "elapsed_ms": round((time.perf_counter() - start) * 1000)}
    assert requests.count(("POST", "/api/focus/start")) == 1, requests
    assert injected and len(rows) == 3 and not rows[-1]["tools_exposed"], rows
    assert result.content.strip() and core.last_action_trace["response_status"] == "succeeded", body
    Path(".zhaoxi/lifehud-v146-reply-live.json").write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(body, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
