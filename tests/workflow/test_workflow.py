from pathlib import Path

import pytest
from pydantic import BaseModel

from zhaoxi.permission.executor import ToolExecutor
from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.workflow.loader import WorkflowLoader
from zhaoxi.workflow.models import WorkflowDefinition, WorkflowStatus
from zhaoxi.workflow.registry import WorkflowRegistry, WorkflowValidationError
from zhaoxi.workflow.runtime import WorkflowRuntime
from zhaoxi.workflow.sqlite import SQLiteWorkflowStore


class ValueInput(BaseModel):
    value: str


class ReadValue(Tool):
    name = "read_value"
    description = "读取测试值。"
    input_model = ValueInput

    async def execute(self, arguments):
        return ToolResult(success=True, content="读取成功。", data={"value": arguments.value})


class WriteValue(ReadValue):
    name = "write_value"
    description = "写入测试值。"
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})

    def __init__(self):
        self.values = []

    async def execute(self, arguments):
        self.values.append(arguments.value)
        return ToolResult(success=True, content="写入成功。", data={"value": arguments.value})


def make_runtime(definition: dict):
    tools = ToolRegistry()
    tools.register(ReadValue())
    write = tools.register(WriteValue())
    workflows = WorkflowRegistry(tools)
    workflows.register(WorkflowDefinition.model_validate(definition))
    return WorkflowRuntime(workflows, ToolExecutor(tools)), write


def simple_definition(tool="read_value"):
    return {
        "id": "test.flow",
        "version": 1,
        "name": "测试流程",
        "inputs": {"value": {"type": "string", "required": True}},
        "steps": [
            {
                "id": "call",
                "type": "tool",
                "tool": tool,
                "arguments": {"value": "$.inputs.value"},
                "output_mapping": {"saved": "$.steps.call.output.data.value"},
                "next": "done",
            },
            {"id": "done", "type": "end", "result": {"value": "$.variables.saved"}},
        ],
    }


async def test_read_workflow_completes_and_maps_output():
    runtime, _ = make_runtime(simple_definition())
    run = await runtime.start("test.flow", {"value": "朝汐"})
    assert run.status == WorkflowStatus.COMPLETED
    assert run.result == {"value": "朝汐"}
    assert [item.type for item in run.events][-1] == "run_completed"


async def test_missing_input_waits_and_resumes_same_run():
    runtime, _ = make_runtime(simple_definition())
    waiting = await runtime.start("test.flow")
    assert waiting.status == WorkflowStatus.WAITING_FOR_INPUT
    completed = await runtime.provide_input(waiting.id, {"value": "补充"})
    assert completed.id == waiting.id
    assert completed.status == WorkflowStatus.COMPLETED


async def test_write_waits_for_permission_and_executes_once():
    runtime, tool = make_runtime(simple_definition("write_value"))
    waiting = await runtime.start("test.flow", {"value": "safe"})
    assert waiting.status == WorkflowStatus.WAITING_FOR_PERMISSION
    assert tool.values == []
    completed = await runtime.approve(waiting.id)
    assert completed.status == WorkflowStatus.COMPLETED
    assert tool.values == ["safe"]


async def test_permission_denial_fails_without_side_effect():
    runtime, tool = make_runtime(simple_definition("write_value"))
    waiting = await runtime.start("test.flow", {"value": "no"})
    denied = await runtime.deny(waiting.id)
    assert denied.status == WorkflowStatus.FAILED
    assert denied.error == "permission_denied"
    assert tool.values == []


async def test_condition_uses_safe_whitelist():
    definition = {
        "id": "test.branch",
        "version": 1,
        "name": "分支",
        "inputs": {"enabled": {"type": "boolean", "required": True}},
        "steps": [
            {"id": "choose", "type": "condition", "expression": {"eq": ["$.inputs.enabled", True]}, "on_true": "yes", "on_false": "no"},
            {"id": "yes", "type": "end", "result": {"answer": "yes"}},
            {"id": "no", "type": "end", "result": {"answer": "no"}},
        ],
    }
    runtime, _ = make_runtime(definition)
    run = await runtime.start("test.branch", {"enabled": False})
    assert run.result == {"answer": "no"}


def test_loader_reads_yaml(tmp_path: Path):
    value = tmp_path / "flow.yaml"
    value.write_text(
        "id: test.yaml\nversion: 1\nname: YAML\nsteps:\n  - id: done\n    type: end\n",
        encoding="utf-8",
    )
    assert WorkflowLoader().load_file(value).id == "test.yaml"


def test_registry_rejects_unknown_tool_and_cycles():
    tools = ToolRegistry()
    registry = WorkflowRegistry(tools)
    with pytest.raises(WorkflowValidationError, match="未知 Tool"):
        registry.register(WorkflowDefinition.model_validate(simple_definition("missing")))

    cycle = {
        "id": "test.cycle",
        "version": 1,
        "name": "循环",
        "steps": [
            {"id": "a", "type": "set", "values": {}, "next": "b"},
            {"id": "b", "type": "set", "values": {}, "next": "a"},
            {"id": "done", "type": "end"},
        ],
    }
    with pytest.raises(WorkflowValidationError, match="循环"):
        WorkflowRegistry().register(WorkflowDefinition.model_validate(cycle))


async def test_sqlite_store_round_trip(tmp_path: Path):
    runtime, _ = make_runtime(simple_definition())
    run = await runtime.start("test.flow")
    store = SQLiteWorkflowStore(tmp_path / "workflow.db")
    await store.save(run)
    restored = await store.get(run.id)
    assert restored is not None
    assert restored.status == WorkflowStatus.WAITING_FOR_INPUT
    assert restored.definition_snapshot.id == "test.flow"


async def test_sqlite_permission_wait_can_resume_after_runtime_restart(tmp_path: Path):
    path = tmp_path / "workflow.db"

    def build():
        tools = ToolRegistry()
        write = tools.register(WriteValue())
        workflows = WorkflowRegistry(tools)
        workflows.register(WorkflowDefinition.model_validate(simple_definition("write_value")))
        runtime = WorkflowRuntime(workflows, ToolExecutor(tools), SQLiteWorkflowStore(path))
        return runtime, write

    first, first_tool = build()
    waiting = await first.start("test.flow", {"value": "once"})
    assert waiting.status == WorkflowStatus.WAITING_FOR_PERMISSION
    assert first_tool.values == []

    restarted, restarted_tool = build()
    completed = await restarted.approve(waiting.id)
    assert completed.status == WorkflowStatus.COMPLETED
    assert restarted_tool.values == ["once"]
