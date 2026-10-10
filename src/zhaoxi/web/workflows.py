"""Owner workflow catalog and persisted definition management; no execution side effects."""
from fastapi import APIRouter, HTTPException
from zhaoxi.workflow.models import WorkflowDefinition
from zhaoxi.workflow.registry import WorkflowValidationError


def workflow_router(core):
    router = APIRouter(prefix="/api/workflows")

    def runtime():
        value = getattr(core, "workflow", None)
        if value is None:
            raise HTTPException(409, "工作流未开启")
        return value

    @router.get("")
    async def catalog():
        value = runtime()
        return {"definitions": value.registry.catalog(),
                "runs": [run.model_dump(mode="json", exclude={"definition_snapshot", "inputs", "outputs"}) for run in await value.store.list(30)]}

    @router.get("/{identity}")
    async def definition(identity: str):
        matches = [d for d in runtime().registry.list() if d.id == identity]
        if not matches:
            raise HTTPException(404, "流程不存在")
        return max(matches, key=lambda d: d.version).model_dump(mode="json")

    @router.put("/{identity}")
    async def save(identity: str, definition: WorkflowDefinition):
        try:
            runtime().registry.manage(identity, definition)
        except WorkflowValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"saved": True}

    @router.delete("/{identity}")
    async def remove(identity: str):
        try:
            runtime().registry.manage(identity)
        except WorkflowValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"removed": True}

    return router
