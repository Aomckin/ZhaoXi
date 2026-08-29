"""Process-local short-term session storage."""

from datetime import datetime, timezone

from zhaoxi.session.base import Session, SessionStore


class InMemorySessionStore(SessionStore):
    """Process-local session store; unrelated to persistent long-term memory."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    async def create(self) -> Session:
        session = Session()
        self._sessions[session.id] = session
        return session

    async def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def save(self, session: Session) -> None:
        session.updated_at = datetime.now(timezone.utc)
        self._sessions[session.id] = session

    async def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    async def list(self) -> list[Session]:
        return list(self._sessions.values())
