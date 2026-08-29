"""Session storage contracts."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from zhaoxi.core.conversation import Conversation


class Session(BaseModel):
    """Metadata and short-term conversation for one running session."""

    model_config = {"arbitrary_types_allowed": True}
    id: str = Field(default_factory=lambda: uuid4().hex)
    conversation: Conversation = Field(default_factory=Conversation)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionStore(ABC):
    @abstractmethod
    async def create(self) -> Session: ...

    @abstractmethod
    async def get(self, session_id: str) -> Session | None: ...

    @abstractmethod
    async def save(self, session: Session) -> None: ...

    @abstractmethod
    async def delete(self, session_id: str) -> bool: ...

    @abstractmethod
    async def list(self) -> list[Session]: ...

