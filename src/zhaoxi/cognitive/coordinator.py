"""Natural-language entrypoint integrating routing, execution, and memory."""

import logging
from dataclasses import dataclass

from zhaoxi.cognitive.memory_decision import AutoMemory, MemoryAction
from zhaoxi.cognitive.router import CognitiveRoute, CognitiveRouter
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.permission.models import PendingConfirmation

logger = logging.getLogger("COGNITIVE")


@dataclass(slots=True)
class CognitiveResponse:
    content: str
    route: CognitiveRoute
    goal_id: str | None = None
    memory_action: MemoryAction = MemoryAction.IGNORE
    permission_confirmation: PendingConfirmation | None = None


class CognitiveCoordinator:
    """Keep input routing separate from post-response memory organization."""

    def __init__(
        self,
        *,
        agent: ZhaoxiAgent,
        router: CognitiveRouter,
        auto_memory: AutoMemory | None = None,
    ) -> None:
        self.agent = agent
        self.router = router
        self.auto_memory = auto_memory

    async def run(self, user_message: str) -> CognitiveResponse:
        decision = await self.router.route(user_message)
        if decision.route == CognitiveRoute.PLAN and self.agent.planner is not None:
            result = await self.agent.run_planned(user_message)
            content = result.content
            goal_id = result.goal_id
        elif decision.route == CognitiveRoute.DIRECT:
            result = await self.agent.run_direct(user_message)
            content = result.content
            goal_id = None
        else:
            if decision.route == CognitiveRoute.PLAN:
                decision.route = CognitiveRoute.TOOL
            result = await self.agent.run(user_message)
            content = result.content
            goal_id = None
        memory_action = MemoryAction.IGNORE
        if self.auto_memory is not None:
            try:
                memory_decision = await self.auto_memory.process(user_message, content)
                memory_action = memory_decision.action
                logger.info("auto_memory action=%s", memory_action.value)
            except Exception as exc:
                logger.warning("auto memory failed; preserving response: %s", exc)
        return CognitiveResponse(
            content=content,
            route=decision.route,
            goal_id=goal_id,
            memory_action=memory_action,
            permission_confirmation=getattr(result, "permission_confirmation", None),
        )
