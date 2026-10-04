"""Isolated HTTP fixture for reply-group rendering and retry; no real model."""
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import uvicorn
from dashboard_fixture import dashboard_core
from zhaoxi.core.agent import AgentResponse
from zhaoxi.core.reply.renderer import commit_reply
from zhaoxi.web.app import create_app

if __name__ == "__main__":
    path = Path(".zhaoxi/reply-group-browser") / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    core, settings = dashboard_core(path)
    core.internal_activity.control.update("presence", {"heartbeat_enabled": False})
    core.conversation.add_user("fixture question")
    commit_reply(core.conversation, "before original[emoji:missing]after original")
    calls = [0]
    async def reply(content, **kwargs):
        calls[0] += 1
        core.conversation.add_user(content)
        service = SimpleNamespace(enabled=False, resolve_tags=lambda tags: SimpleNamespace(status="matched", emoji_id="fixture"))
        sequence, _ = commit_reply(core.conversation, f"before retry {calls[0]}[emoji:test]after retry {calls[0]}\n\nlast paragraph", service)
        return AgentResponse(content=sequence.visible_text, request_id=f"fixture-{calls[0]}", steps=1)
    core.run_natural = reply
    uvicorn.run(create_app(agent=core, settings=settings), host="127.0.0.1", port=18768)
