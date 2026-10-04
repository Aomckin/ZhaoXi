"""Decision as agency: same-model reply metadata and optional context, no router."""

from datetime import UTC, datetime, timedelta
import json
import logging
import re
from typing import Protocol
from uuid import uuid4

from .models import DecisionAwarenessTrace, DecisionMode

logger = logging.getLogger("DECISION")

AWARENESS_PROMPT = """先结合本轮文字、图片和前几轮对话确认正在选择什么。图片已给出的价格、档位、功能先直接读取；前文已明确的需求不再追问。仅说“帮我想想”但没有可读选项或问题对象时，先自然接住并问清一件事，不凭“好好考虑”这类措辞进入 FRAME 或检索整套资料。购买建议先回答要不要，再给档位方向；只为会改变结论的事实缺口按需查询。不要为展示了解用户同时调用 search_memories 和 read_decision_context(memory) 重复读同一资料。比较期限与总价时，不假设年费可抵扣买断、后续升级有优惠或未核实的退费政策。买断的回本年数只是假设价格和功能不变的算术门槛，不证明用户能持续用到那一天。未确认使用年限、实际设备或关键需求时，不用“肯定用几年”“往后白赚”替用户补事实；给可逆的暂定方向，只留下一个会改变建议的关键问题。不要把平台宣传的功能当成用户已经具备的需求，也不要先向用户汇报无结果的查询流水账。
当暗苟面临真正的选择时，先判断值不值得他继续花注意力。小而可逆的选择用 PICK 直接替他选，给一个答案且收住，不列备选、不补条件分支、不再询问偏好，也无需解释自己在盲选；没有明显差异也可主观拍一个，不因缺规则或不重要的信息升级、追问。能形成方向时用 ADVISE，先给明确建议，再给很短的原因。长期、高影响、不可逆或核心价值取舍用 FRAME，即使要求“直接替我决定”也不能退化成 PICK；可以给倾向，但不能替用户完成最后价值判断：先主动查齐能查的资料，压缩关键事实和真正冲突，只留下最后属于暗苟的价值判断，不能只说“你自己决定”。只陈述已核实事实，缺失标为未核实；不得臆造面试已到最后一轮、今日空闲、补丁已收尾、用户开销或公司/合同条件。反思或闲聊无需机械拍板。
当前明确表达、现实事实、近期认识优先于长期偏好、原则、真实选择历史和暂时推测。历史选择是弱证据；一次选择或 Override 不能变成长期规则。可暂时推测但不能编造永久偏好；predicted_user_choice 和你的 agent_recommendation 可以不同。用户改变选择就接受，不引用旧规则争论。
需要什么再查什么：涉及下午安排、是否打断今日主线等中等影响事项用 ADVISE，先确认本轮相关 Agenda/Current Cognition；已提供的相关近期摘要可使用，具体日程未知再按需读取（FAST 用 decision 升级），不能因完成一个补丁就猜今日主线全部完成或今天有空；Offer 用 FRAME，先按需查相关 Memory/Principles/岗位资料；可用 read_decision_context 选择 sources 查询，再按需使用其他工具。不要全量预读，不为小选择检索。建议购买不等于授权付款，自动行动仍经过 Permission/Guard/Confirmation。
最终回复必须输出 JSON 对象 {"reply":"自然台词","awareness":{"mode":"PICK","agent_recommendation":"选择","context_sources":[]},"escalation":null}，不使用 XML。awareness 是同一回复的旁产物，不是额外分析。凡是你在替用户选择或给选择建议，mode 必须用 PICK/ADVISE/FRAME；只有真正没有选择的闲聊/反思用 NONE。无关键词但正在挑东西也可以 PICK。FAST 缺必要资料时填 escalation={"kind":"decision","reason":"缺什么","trigger_span":"本轮逐字原文"}，reply 留空；STANDARD 直接调用真实工具补资料，最终才给 JSON，不填 escalation。awareness 的 predicted_user_choice/agent_recommendation 是不超过200字的字符串或 null；context_sources/context_refs/principle_ids/guard_flags 是字符串数组（没有则 []），不是对象或解释文字；不要填无意义的占位字段。
mode 是 NONE/PICK/ADVISE/FRAME；可选 feedback={"decision_id":"本轮给出的待反馈ID","user_final_choice":"用户明确最终选择","overridden":true,"outcome":null}。NONE 可用于接受反馈。只引用本轮实际资料 ID，不伪造检索、Guard 或用户最终选择；普通闲聊不用标记。"""

_MARKER = re.compile(r"<decision-awareness\b[^>]*>(.*?)(?:</decision-awareness\s*>|$)", re.S | re.I)


def split_awareness(content: str) -> tuple[str, DecisionAwarenessTrace | None, str | None]:
    matches = list(_MARKER.finditer(content))
    clean = _MARKER.sub("", content).strip()
    # A truncated opening tag must never reach chat, persistence or emoji DSL.
    clean = re.sub(r"<decision-awareness\b[^>]*$", "", clean, flags=re.I).strip()
    if not matches:
        return clean, None, None
    try:
        value = DecisionAwarenessTrace.from_reply(json.loads(matches[-1].group(1).strip()))
        return clean, value, None
    except ValueError:
        return clean, None, "invalid_metadata"


class DecisionContextProvider(Protocol):
    """Future location/image/LifeHUD adapters implement evidence reads only."""

    async def retrieve(self, query: str, *, limit: int) -> list[dict]: ...


def choice_scope() -> str:
    from zhaoxi.cognitive_stream.turn import current_turn
    turn = current_turn()
    if turn:
        event = turn.trigger_event
        return ":".join([turn.audience, event.channel or event.source,
                         event.session_id or "", event.conversation_id or ""])
    return "owner:desktop:local"


class DecisionAwareness:
    def __init__(self, *, history=None, principles=None, agenda=None, cognition=None, memory=None):
        self.history = history
        self.principles = principles
        self.agenda = agenda
        self.cognition = cognition
        self.memory = memory
        self.providers: dict[str, DecisionContextProvider] = {}
        self.recent_traces: list[dict] = []

    def register_context_provider(self, name: str, provider: DecisionContextProvider) -> None:
        if name in {"agenda", "current_cognition", "memory", "principles", "choice_history"}:
            raise ValueError("Built-in source cannot be replaced")
        self.providers[name] = provider

    def pending_choice(self, conversation) -> dict | None:
        for message in reversed(conversation.messages[-12:]):
            identity = message.metadata.get("decision_awareness")
            if identity and identity.get("scope") == choice_scope():
                return identity
        # Channel replies use a transient Conversation; use the same scoped
        # history instead of binding decision semantics to Desktop or QQ.
        if self.history:
            try:
                rows = self.history.list(limit=1, scope=choice_scope())
                if rows and datetime.fromisoformat(rows[0]["timestamp"]) > datetime.now(UTC) - timedelta(days=1):
                    return rows[0]
            except (OSError, ValueError, TypeError) as exc:
                logger.warning("pending choice unavailable: %s", type(exc).__name__)
        return None

    def prompt(self, conversation) -> str:
        value = AWARENESS_PROMPT
        if self.providers:
            value += "\n已注册按需扩展资料来源：" + ", ".join(self.providers)
        if pending := self.pending_choice(conversation):
            value += "\n待反馈选择（仅用户本轮明确承接才记录反馈）：" + json.dumps(
                {"decision_id": pending["decision_id"], "suggestion": pending.get("suggestion")},
                ensure_ascii=False)
        return value

    def commit(self, trace: DecisionAwarenessTrace | None, error: str | None, conversation, builder) -> dict | None:
        from zhaoxi.cognitive_stream.turn import current_turn
        turn = current_turn()
        if turn and turn.audience != "owner":
            return None
        if trace is None:
            if error:
                logger.warning("decision metadata ignored: %s", error)
            return None
        from zhaoxi.core.message import Role
        # Receipts come from real successful tools in this turn. Model metadata
        # cannot claim that Memory/Agenda/Principles were read when they were not.
        turn_messages = []
        for message in reversed(conversation.messages):
            if message.role in {Role.USER, Role.EXTERNAL}:
                user = message
                break
            turn_messages.append(message)
        else:
            return None
        available = {"current_input": ["input:" + user.message_id],
                     **user.metadata.get("decision_context_sources", {})}
        if user.images:
            available["current_image"] = ["image:" + user.message_id + ":" + str(index)
                                          for index in range(len(user.images))]
        guard_flags = []
        consulted = {source: list(refs) for source, refs in user.metadata.get("decision_context_sources", {}).items()}
        if user.images:
            consulted["current_image"] = available["current_image"]
        for message in turn_messages:
            if message.role is not Role.TOOL:
                continue
            try:
                result = json.loads(message.content or "{}")
            except ValueError:
                continue
            guard_flags.extend(result.get("metadata", {}).get("decision_guard_flags", []))
            if result.get("success"):
                data = result.get("data")
                if message.name == "read_decision_context" and isinstance(data, dict):
                    for source, rows in data.get("sources", {}).items():
                        refs = [row["ref"] for row in rows if row.get("ref")]
                        available.setdefault(source, []).extend(refs)
                        consulted.setdefault(source, []).extend(refs)
                else:
                    available["tool"] = [*available.get("tool", []), "tool:" + str(message.name)]
                    if message.name == "search_memories":
                        refs = ["memory:" + row["id"] for row in data
                                if isinstance(row, dict) and isinstance(row.get("id"), str)] if isinstance(data, list) else []
                        available.setdefault("memory", []).extend(refs)
                        consulted.setdefault("memory", []).extend(refs)
        # Separate actual receipts from the subset the main reply reports using.
        trace.context_sources = [source for source in dict.fromkeys([*trace.context_sources, *consulted]) if source in available]
        refs = {ref for source in trace.context_sources for ref in available[source]}
        trace.context_refs = list(dict.fromkeys([*[ref for ref in trace.context_refs if ref in refs],
            *[ref for values in consulted.values() for ref in values]]))
        valid_principles = {ref.removeprefix("principles:") for ref in available.get("principles", [])}
        trace.principle_ids = [identity for identity in trace.principle_ids if identity in valid_principles]
        trace.guard_flags = list(dict.fromkeys(guard_flags))
        scope = choice_scope()
        if trace.feedback:
            pending = self.pending_choice(conversation)
            if self.history and pending and pending["decision_id"] == trace.feedback.decision_id:
                try:
                    self.history.feedback(scope=scope, final=trace.feedback.user_final_choice,
                        decision_id=trace.feedback.decision_id, overridden=trace.feedback.overridden,
                        outcome=trace.feedback.outcome)
                except (ValueError, OSError) as exc:
                    logger.warning("choice feedback not saved: %s", type(exc).__name__)
            else:
                trace.feedback = None
        row = {**trace.model_dump(mode="json"), "decision_id": uuid4().hex,
               "scope": scope, "timestamp": datetime.now(UTC).isoformat(),
               "summary": (user.content or "")[:160], "suggestion": trace.agent_recommendation}
        if trace.mode is not DecisionMode.NONE and self.history:
            try:
                self.history.record(row["decision_id"], trace, row["summary"], scope=scope)
            except OSError as exc:
                logger.warning("choice history not saved: %s", type(exc).__name__)
        self.recent_traces.append(row)
        self.recent_traces[:] = self.recent_traces[-20:]
        from zhaoxi.observability import current_trace
        if runtime := current_trace():
            runtime.decision_used = trace.mode is not DecisionMode.NONE
            runtime.emit("decision_awareness", "decision", "success", "已形成生活判断",
                         metadata=row)
        return row

    def diagnostics(self) -> dict:
        return {"decision_mode": "agency", "latest": self.recent_traces[-1] if self.recent_traces else None,
                "recent": list(self.recent_traces),
                "choice_history": self.history.list() if self.history else [],
                "context_providers": list(self.providers)}
