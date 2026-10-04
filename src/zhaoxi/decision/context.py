"""Model-selected, bounded context reads; no intent detection or model calls."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

from zhaoxi.tools.base import Tool, ToolResult
from .awareness import choice_scope
from .principles import relevance


class DecisionContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)
    sources: list[str] = Field(min_length=1, max_length=8,
        description="只选本题需要的 agenda/current_cognition/memory/user_principles/decision_journal/choice_history（principles兼容别名） 或已注册扩展来源。")
    limit: int = Field(default=5, ge=1, le=8)


class ReadDecisionContext(Tool):
    name = "read_decision_context"
    description = "按需读取与当前选择相关的日程、近期认知、记忆、明确原则或弱证据选择历史；不作决策、不执行行动。低价值选择上下文足够时无需调用。"
    input_model = DecisionContextInput
    group = "decision_context"
    persistent = True

    def __init__(self, awareness):
        self.awareness = awareness

    async def execute(self, arguments: DecisionContextInput) -> ToolResult:
        from .learning_models import private_owner
        if not private_owner():
            return ToolResult(success=False, content="个人选择资料仅供 Owner 会话使用。", error="owner_only")
        sources, errors = {}, {}
        for source in dict.fromkeys(arguments.sources):
            try:
                sources[source] = await self._read(source, arguments.query, arguments.limit)
            except Exception as exc:
                errors[source] = type(exc).__name__
        return ToolResult(success=bool(sources), content="本轮按需资料；空结果不代表从未发生，选择历史只作弱证据。",
                          data={"sources": sources, "errors": errors},
                          error="context_unavailable" if not sources else None)

    async def _read(self, source: str, query: str, limit: int) -> list[dict]:
        service = self.awareness
        if source in {"principles", "user_principles"} and service.user_principles:
            result = [{"ref": source + ":" + r['id'], **r} for r in service.user_principles.retrieve(query, limit)]
            if service.principle_archive:
                result.extend(service.principle_archive.fragments(query, max(1, limit - len(result))))
            return result[:limit]
        if source == "decision_journal" and service.journal:
            return [{"ref": "decision_journal:" + r['id'], "authority": "agent_experience_not_user_quote", **r}
                    for r in service.journal.retrieve(query, limit)]
        if source in {"principles", "user_principles"} and service.principles:
            return [{"ref": source + ":" + rule.id, "id": rule.id,
                     "principle": rule.default, "basis": rule.reasons,
                     "exceptions": rule.exceptions, "source": rule.source}
                    for rule in service.principles.retrieve_principles(query, limit=limit)]
        if source == "choice_history" and service.history:
            return [{"ref": "choice_history:" + row["decision_id"], **row}
                    for row in service.history.retrieve(query, scope=choice_scope(), limit=limit)]
        if source == "memory" and service.memory:
            return [{"ref": "memory:" + item.record.id, "content": item.record.content[:500],
                     "source": item.record.source, "confidence": item.record.confidence}
                    for item in (await service.memory.retrieve(query))[:limit]]
        if source == "current_cognition" and service.cognition:
            state = service.cognition.state()
            threads = [item for item in state.threads if item.status != "resolved"
                       and item.manual_state not in {"RESOLVED", "DISMISSED"}]
            threads.sort(key=lambda item: (-relevance(query, item.title + item.summary), -item.salience))
            result = [{"ref": "current_cognition:overview", "summary": state.overview}] if state.overview else []
            result.extend({"ref": "current_cognition:" + item.key,
                           "title": item.title, "summary": item.summary}
                          for item in threads if relevance(query, item.title + item.summary))
            return result[:limit]
        if source == "agenda" and service.agenda:
            now = datetime.now(service.agenda.timezone)
            items = service.agenda.list("active")
            today = now.date()
            relevant = [item for item in items if item.scope == "today"
                        or (item.start_at and item.start_at.astimezone(service.agenda.timezone).date() == today)
                        or (item.due_at and item.due_at.astimezone(service.agenda.timezone).date() == today)
                        or relevance(query, item.title + " " + item.note)]
            relevant.sort(key=lambda item: (-relevance(query, item.title + " " + item.note), -item.priority))
            return [{"ref": "agenda:" + item.id, "type": item.type.value, "title": item.title,
                     "scope": item.scope, "start_at": str(item.start_at) if item.start_at else None,
                     "end_at": str(item.end_at) if item.end_at else None,
                     "due_at": str(item.due_at) if item.due_at else None,
                     "note": item.note[:300]} for item in relevant[:limit]]
        if source in service.providers:
            rows = await service.providers[source].retrieve(query, limit=limit)
            return [{"ref": str(row.get("ref", source + ":" + str(index)))[:150],
                     "content": str(row.get("content", ""))[:500]} for index, row in enumerate(rows[:limit])]
        raise ValueError("Source unavailable or unregistered")

def relevant_cognition(service, query: str) -> str:
    """Reuse the journal, but expose only its overview and related threads."""
    state = service.state()
    threads = [item for item in state.threads if item.status != "resolved"
               and item.manual_state not in {"RESOLVED", "DISMISSED"}
               and relevance(query, item.title + item.summary)]
    threads.sort(key=lambda item: (-relevance(query, item.title + item.summary), -item.salience))
    lines = [state.overview] if state.overview else []
    lines.extend(item.title + ": " + item.summary for item in threads[:3])
    return "[Current Cognition]\n" + "\n".join(lines) + "\n[/Current Cognition]"
