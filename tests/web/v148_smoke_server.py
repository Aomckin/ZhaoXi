"""Isolated v1.4.8 browser fixture: generated history and inert workflow."""
import asyncio
from pathlib import Path
from uuid import uuid4
import uvicorn
from dashboard_fixture import dashboard_core
from zhaoxi.core.conversation import Conversation
from zhaoxi.session.sqlite import SQLiteSessionStore
from zhaoxi.session.base import Session
from zhaoxi.workflow.registry import WorkflowRegistry
from zhaoxi.workflow.models import WorkflowDefinition
from zhaoxi.workflow.runtime import WorkflowRuntime
from zhaoxi.web.app import create_app

if __name__ == '__main__':
    path = Path('.zhaoxi/v148-browser') / uuid4().hex
    path.mkdir(parents=True)
    core, settings = dashboard_core(path)
    core.internal_activity.control.update('presence', {'heartbeat_enabled':False})
    core.conversation = Conversation(max_messages=40)
    core.session_store = SQLiteSessionStore(path / 'session.db')
    core.session_record = Session(id='local', conversation=core.conversation)
    for index in range(60):
        core.conversation.add_user(f'USER-HISTORY-{index}')
        core.conversation.add_assistant(f'ASSISTANT-HISTORY-{index}')
    core.session_store.save_sync(core.session_record)
    registry = WorkflowRegistry()
    registry.configure_management(path / 'workflows.json')
    registry.manage('fixture', WorkflowDefinition(id='fixture',version=1,name='隔离演示流程',steps=[{'id':'done','type':'end'}]))
    core.workflow = WorkflowRuntime(registry, core.tool_executor)
    uvicorn.run(create_app(agent=core, settings=settings), host='127.0.0.1', port=18770)
