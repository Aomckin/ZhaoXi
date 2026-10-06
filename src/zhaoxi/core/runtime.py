"""Application services owned by one Agent runtime, separate from turn execution.

RuntimeService keeps the established agent.<service> API as a forwarding view;
there is exactly one stored value, on agent.runtime.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar, overload

if TYPE_CHECKING:
    from zhaoxi.core.tool_retry import ToolRetryContext
    from zhaoxi.config.settings import Settings
    from zhaoxi.memory.service import MemoryService
    from zhaoxi.archive.service import ArchiveService
    from zhaoxi.agenda.service import AgendaService
    from zhaoxi.current_cognition import CurrentCognitionService, CurrentCognitionMaintainer
    from zhaoxi.cognitive_stream import ExperienceStream, CognitiveIngress, AttentionRetriever, SessionProjector
    from zhaoxi.session.base import Session, SessionStore
    from zhaoxi.reflection.service import ReflectionService
    from zhaoxi.reflection.periods import PeriodResolver
    from zhaoxi.decision.service import DecisionService
    from zhaoxi.decision.learning import DecisionLearning
    from zhaoxi.decision.follow_up import DecisionFollowUp
    from zhaoxi.internal_activity.runtime import InternalActivityRuntime
    from zhaoxi.reliability.storage import BackupManager
    from zhaoxi.perception.runtime import PerceptionRuntime
    from zhaoxi.expression import EmojiService, EmojiManager
    from zhaoxi.cognitive.coordinator import CognitiveCoordinator
    from zhaoxi.proactive.heartbeat import TidalHeartbeat
    from zhaoxi.proactive.worker import DecisionWorker
    from zhaoxi.proactive.beat import ConversationBeatLoop


@dataclass(slots=True)
class AgentRuntime:
    allow_multi_model_calls: bool = False
    tool_retry_context: ToolRetryContext | None = None
    settings: Settings | None = None
    memory_service: MemoryService | None = None
    archive: ArchiveService | None = None
    agenda: AgendaService | None = None
    current_cognition: CurrentCognitionService | None = None
    current_cognition_maintainer: CurrentCognitionMaintainer | None = None
    experience_stream: ExperienceStream | None = None
    cognitive_ingress: CognitiveIngress | None = None
    attention_retriever: AttentionRetriever | None = None
    session_projector: SessionProjector | None = None
    session_store: SessionStore | None = None
    session_record: Session | None = None
    reflection: ReflectionService | None = None
    reflection_periods: PeriodResolver | None = None
    decision_service: DecisionService | None = None
    decision_learning: DecisionLearning | None = None
    decision_follow_up: DecisionFollowUp | None = None
    internal_activity: InternalActivityRuntime | None = None
    backup_manager: BackupManager | None = None
    perception: PerceptionRuntime | None = None
    emoji_service: EmojiService | None = None
    emoji_manager: EmojiManager | None = None
    cognitive: CognitiveCoordinator | None = None
    proactive_heartbeat: TidalHeartbeat | None = None
    proactive_worker: DecisionWorker | None = None
    conversation_continuation: ConversationBeatLoop | None = None


T = TypeVar("T")


class RuntimeService(Generic[T]):
    """Compatibility alias for a typed runtime field; never stores a second copy."""
    def __init__(self, name: str):
        self.name = name

    @overload
    def __get__(self, agent: None, owner: type | None = None) -> RuntimeService[T]: ...

    @overload
    def __get__(self, agent: Any, owner: type | None = None) -> T: ...

    def __get__(self, agent, owner=None):
        return self if agent is None else getattr(agent.runtime, self.name)

    def __set__(self, agent, value: T) -> None:
        setattr(agent.runtime, self.name, value)
