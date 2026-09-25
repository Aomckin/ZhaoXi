"""Opt-in decision evaluation with narrow context and conservative fallback."""

import logging
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from zhaoxi.agenda.models import AgendaType
from zhaoxi.core.message import Message, Role
from zhaoxi.observability import current_trace

from .guard import guard
from .models import DecisionContext, DecisionLevel, DecisionProposal, DecisionResult, is_directional_verdict
from .recorder import DecisionRecorder
from .rules import RuleStore

logger = logging.getLogger("DECISION")
INTENT = re.compile(r"要不要|该不该|选哪个|选哪|值不值得|继续吗|去不去|买不买|接不接|接吗|怎么选|怎么弄|替我决定|帮我选|你直接定|帮我拍板|别分析了.{0,6}选|到底.{0,12}(?:去|做|选)")
IMPLICIT_TENSION = re.compile(r"(?:岗位|offer|工作|项目).{0,80}(?:但|可是|然而).{0,80}(?:冲突|长期占用|取舍|两难)", re.I)
DECIDE_FOR_ME = re.compile(r"替我决定|你直接定|帮我拍板|别分析了.{0,6}选|帮我选一个")
OVERRIDE = re.compile(r"^(?:不[，,、 ]|算了[，,、 ]|我还是|这个规则别用了|不按这个来)")
DOMAIN_MARKERS = {"schedule": ("活动", "会议", "主线", "日程"),
                  "job_search": ("岗位", "投递", "秋招", "校招", "offer", "面试", "宣讲", "薪资"),
                  "purchase": ("买", "购", "消费", "付款"),
                  "daily": ("午饭", "晚饭", "吃", "餐", "外卖")}

SCHEMA = {"type": "function", "function": {"name": "classify_decision",
          "description": "只依据提供的事实与规则输出结构化决策，不执行任何行动。",
          "parameters": DecisionProposal.model_json_schema()}}


class DecisionService:
    def __init__(self, provider, *, rule_directory: str | Path, data_directory: str | Path,
                 agenda=None, current_cognition=None, memory_retriever=None,
                 tool_catalog: list[dict] | None = None, timezone: str = "Asia/Shanghai"):
        self.provider = provider
        self.rules = RuleStore(rule_directory)
        self.recorder = DecisionRecorder(data_directory)
        self.agenda = agenda
        self.current_cognition = current_cognition
        self.memory_retriever = memory_retriever
        self.tool_catalog = tool_catalog or []
        self.timezone = ZoneInfo(timezone)
        self.last_result: DecisionResult | None = None
        self.last_context: DecisionContext | None = None
        self.last_triggered = False

    def should_evaluate(self, text: str, *, planner_requested: bool = False) -> bool:
        return planner_requested or bool(INTENT.search(text) or IMPLICIT_TENSION.search(text))

    def is_override(self, text: str) -> bool:
        return (self.last_result is not None and self.last_result.level != DecisionLevel.L2
                and bool(OVERRIDE.search(text.strip())))

    def accept_override(self, text: str) -> dict:
        assert self.last_result is not None
        row = self.recorder.override(self.last_result.decision_id, text.strip())
        self.last_result = None
        return row

    @staticmethod
    def domain(text: str) -> str:
        lower = text.casefold()
        return next((domain for domain, markers in DOMAIN_MARKERS.items()
                     if any(marker in lower for marker in markers)), "general")

    async def context(self, text: str, mode: str) -> DecisionContext:
        domain = self.domain(text)
        context = DecisionContext(current_time=datetime.now(self.timezone), user_request=text[:1000],
                                  decision_mode=mode, matched_rules=self.rules.retrieve(text, domain))
        if self.agenda:
            try:
                items = self.agenda.list("active")
                context.today_mainline = next((item.title for item in items
                    if item.type == AgendaType.FOCUS and not item.secondary
                    and (item.scope == "today" or item.created_at.date() == context.current_time.date())), None)
                context.schedule = [f"{item.title}: {item.start_at or item.due_at or ''}"[:180]
                                    for item in items if item.type != AgendaType.FOCUS][:6]
            except Exception as exc:
                logger.warning("agenda decision read failed type=%s", type(exc).__name__)
                context.current_constraints.append("日程暂时无法核实")
        if self.current_cognition:
            try:
                context.short_term_note = self.current_cognition.snapshot()[:700]
            except Exception as exc:
                logger.warning("current cognition decision read failed type=%s", type(exc).__name__)
                context.current_constraints.append("近期状态暂时无法核实")
        if self.memory_retriever:
            try:
                memories = await self.memory_retriever.retrieve(text)
                context.relevant_memories = [item.record.content[:250] for item in memories[:3]]
            except Exception as exc:
                logger.warning("decision memory read failed type=%s", type(exc).__name__)
        context.available_tools = [str(item.get("name")) for item in self.tool_catalog
                                   if item.get("enabled") and item.get("available")][:20]
        return context

    async def evaluate(self, user_input: str, conversation_context=None, mode: str = "normal",
                       *, planner_requested: bool = False, forced_level: DecisionLevel | None = None,
                       record: bool = True) -> DecisionResult | None:
        self.last_triggered = self.should_evaluate(user_input, planner_requested=planner_requested)
        if not self.last_triggered:
            return None
        mode = "decide_for_me" if DECIDE_FOR_ME.search(user_input) else mode
        context = await self.context(user_input, mode)
        self.last_context = context
        trace = current_trace()
        if trace:
            trace.emit("decision_started", "decision", "running", "正在判断…")
        prompt = ("你只做决策分类，不扮演角色、不调用业务工具。只使用输入中的事实和规则，不编造用户偏好。"
                  "L0 仅限明确规则、低风险可逆且无疑问；普通有依据的可逆问题 L1；长期方向、正式 Offer、"
                  "高撤销成本、规则冲突或关键信息不足 L2。L2 不给结论，提供一个核心问题。"
                  "'不想做'可能是启动阻力也可能是稳定否定，不得只凭语气判断。"
                  "L0/L1 的 decision 必须是明确的方向性结论，如‘现在不开这瓶可乐’或‘现在开一瓶’，"
                  "严禁输出‘是否……’‘要不要……’等疑问句或把问题复述为建议。"
                  "rule_ids 只能引用 matched_rules 中的 ID。reasons 最多两条。只调用 classify_decision。")
        try:
            async def classify(instruction: str) -> DecisionProposal:
                response = await self.provider.generate([
                    Message(role=Role.SYSTEM, content=instruction),
                    Message(role=Role.USER, content=context.model_dump_json(exclude_none=True))], [SCHEMA])
                call = next(call for call in response.tool_calls if call.name == "classify_decision")
                return DecisionProposal.model_validate(call.arguments)
            proposal = await classify(prompt)
            if proposal.level != DecisionLevel.L2 and not is_directional_verdict(proposal.decision):
                proposal = await classify(prompt + "\n上一结果没有给出方向。请重新判断，给一个陈述句结论；若确实不能决定，升为 L2。")
        except Exception as exc:
            logger.warning("decision classifier failed type=%s", type(exc).__name__)
            proposal = DecisionProposal(level=DecisionLevel.L2, domain=self.domain(user_input),
                                        reasons=["暂时无法可靠核实判断依据。"],
                                        core_question="先确认哪些条件对你最重要？", uncertain=True)
        valid_ids = {rule.id for rule in context.matched_rules}
        proposal.rule_ids = [rule_id for rule_id in proposal.rule_ids if rule_id in valid_ids]
        proposal.domain = self.domain(user_input)
        metadata = next((item for item in self.tool_catalog if item.get("name") == proposal.action), None)
        result = guard(proposal, context, forced_level=forced_level, tool_metadata=metadata)
        result.context_sources = [name for name, value in (("agenda", context.schedule or context.today_mainline),
            ("current_cognition", context.short_term_note), ("memory", context.relevant_memories),
            ("rules", context.matched_rules)) if value]
        self.last_result = result
        if record:
            self.recorder.record(result, f"{result.domain}: {result.decision or result.core_question or result.level.value}")
        if trace:
            trace.emit("decision_finished", "decision", "success", "已经决定。",
                       metadata={"decision_id": result.decision_id, "domain": result.domain,
                                 "level": result.level.value, "rule_count": len(result.rule_ids),
                                 "upgraded": bool(result.upgraded_from)})
        return result

    def diagnostics(self) -> dict:
        return {"triggered": self.last_triggered,
                "result": self.last_result.model_dump(mode="json") if self.last_result else None,
                "context": self.last_context.model_dump(mode="json") if self.last_context else None,
                "candidates": self.recorder.candidates()}
