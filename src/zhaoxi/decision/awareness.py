"""Decision as agency: same-model reply metadata and optional context, no router."""

from datetime import UTC, datetime, timedelta
import json
import logging
import re
from typing import Protocol
from uuid import uuid4, uuid5, NAMESPACE_URL

from .models import DecisionAwarenessTrace, DecisionMode
from .question import question_issue
from .learning_models import private_owner

logger = logging.getLogger("DECISION")

AWARENESS_PROMPT = """先结合本轮文字、图片和前几轮对话确认正在选择什么。图片已给出的价格、档位、功能先直接读取；前文已明确的需求不再追问。仅说“帮我想想”但没有可读选项或问题对象时，先自然接住并问清一件事，不凭“好好考虑”这类措辞进入 FRAME 或检索整套资料。购买建议先回答要不要，再给档位方向；只为会改变结论的事实缺口按需查询。不要为展示了解用户同时调用 search_memories 和 read_decision_context(memory) 重复读同一资料。比较期限与总价时，不假设年费可抵扣买断、后续升级有优惠或未核实的退费政策。买断的回本年数只是假设价格和功能不变的算术门槛，不证明用户能持续用到那一天。未确认使用年限、实际设备或关键需求时，不用“肯定用几年”“往后白赚”替用户补事实；给可逆的暂定方向，只留下一个会改变建议的关键问题。不要把平台宣传的功能当成用户已经具备的需求，也不要先向用户汇报无结果的查询流水账。
当暗苟面临真正的选择时，先判断值不值得他继续花注意力。小而可逆的选择用 PICK 直接替他选，给一个答案且收住，不列备选、不补条件分支、不再询问偏好，也无需解释自己在盲选；没有明显差异也可主观拍一个，不因缺规则或不重要的信息升级、追问。能形成方向时用 ADVISE，先给明确建议，再给很短的原因。长期、高影响、不可逆或核心价值取舍用 FRAME，即使要求“直接替我决定”也不能退化成 PICK；可以给倾向，但不能替用户完成最后价值判断：先主动查齐能查的资料，压缩关键事实和真正冲突，只留下最后属于暗苟的价值判断，不能只说“你自己决定”。只陈述已核实事实，缺失标为未核实；不得臆造面试已到最后一轮、今日空闲、补丁已收尾、用户开销或公司/合同条件。反思或闲聊无需机械拍板。
当前明确表达、现实事实、近期认识优先于长期偏好、原则、真实选择历史和暂时推测。历史选择是弱证据；一次选择或 Override 不能变成长期规则。可暂时推测但不能编造永久偏好；predicted_user_choice 和你的 agent_recommendation 可以不同。用户改变选择就接受，不引用旧规则争论。
需要什么再查什么：涉及下午安排、是否打断今日主线等中等影响事项用 ADVISE，先确认本轮相关 Agenda/Current Cognition；已提供的相关近期摘要可使用，具体日程未知再按需读取（FAST 用 decision 升级），不能因完成一个补丁就猜今日主线全部完成或今天有空；Offer 用 FRAME，先按需查相关 Memory/Principles/岗位资料；可用 read_decision_context 选择 sources 查询，再按需使用其他工具。不要全量预读，不为小选择检索。建议购买不等于授权付款，自动行动仍经过 Permission/Guard/Confirmation。
新决策必须填 decision_kind=NEW 与自足的 decision_question（情境、选择对象和必要约束），不把建议当问题。纠正事实填 CORRECTION、普通执行指令填 EXECUTION、同题承接填 CONTINUATION，这些不新增选择记录；闲聊填 NONE。不明确是否真实新取舍时 mode=NONE，不凭自己给了建议制造决策。只有 NEW 且问题足够明确才能登记。decision_question 是先抽象后入库的问题描述，必须脱离当前聊天也能读懂：用中性的一两句明确情境、选择对象及已知的必要约束；省略称呼、口头语和指令语气，补全“这件事”“那个”的实际对象，不编造上下文。不得逐字摘抄本轮消息，也不以建议充当问题。若本轮只是“狗子，你去帮我采购无糖可乐吧”，这是 EXECUTION，不能因为自己附加了数量建议而登记 ADVISE。若上下文确实另有新取舍，例如补购无糖可乐时要确定规格与数量，问题可以写“本次补购无糖可乐，应选什么包装规格和购买数量？”，建议另填“2L 两瓶”。“填表已有对应内容，测评不是投递时做”是 CORRECTION，不新增问题。信息不足以写清问题时 decision_question=null，不用原话或泛泛的“如何选择”占位。
最终回复必须输出 JSON 对象 {"reply":"自然台词","awareness":{"mode":"PICK","decision_kind":"NEW","decision_question":"在明确情境下选择哪个方案","agent_recommendation":"选择","context_sources":[]},"escalation":null}，不使用 XML。awareness 是同一回复的旁产物，不是额外分析。凡是你在替用户选择或给选择建议，mode 必须用 PICK/ADVISE/FRAME；只有真正没有选择的闲聊/反思用 NONE。无关键词但正在挑东西也可以 PICK。FAST 缺必要资料时填 escalation={"kind":"decision","reason":"缺什么","trigger_span":"本轮逐字原文"}，reply 留空；STANDARD 直接调用真实工具补资料，最终才给 JSON，不填 escalation。awareness 的 predicted_user_choice/agent_recommendation 是不超过200字的字符串或 null；context_sources/context_refs/principle_ids/guard_flags 是字符串数组（没有则 []），不是对象或解释文字；不要填无意义的占位字段。
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
        self.user_principles = None
        self.journal = None
        self.principle_archive = None
        self.follow_up = None
        self.providers: dict[str, DecisionContextProvider] = {}
        self.recent_traces: list[dict] = []

    def register_context_provider(self, name: str, provider: DecisionContextProvider) -> None:
        if name in {"agenda", "current_cognition", "memory", "principles", "choice_history", "user_principles", "user_archive", "decision_journal"}:
            raise ValueError("Built-in source cannot be replaced")
        self.providers[name] = provider

    def pending_choice(self, conversation) -> dict | None:
        if not private_owner():
            return None
        for message in reversed(conversation.messages[-12:]):
            identity = message.metadata.get("decision_awareness")
            if (identity and identity.get("scope") == choice_scope()
                    and identity.get("registration_status", "recordable") in {"recordable", "recorded"}):
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

    def feedback_candidates(self, conversation):
        if not private_owner():
            return []
        try:
            rows = self.history.list(limit=5, scope=choice_scope()) if self.history else []
            rows = [r for r in rows if datetime.fromisoformat(r['timestamp']) > datetime.now(UTC) - timedelta(days=30)]
            if rows:
                return rows
        except (OSError, ValueError, TypeError):
            logger.warning('feedback candidates unavailable')
        pending = self.pending_choice(conversation)
        return [pending] if pending else []

    def prompt(self, conversation, *, unified=False, slim=False) -> str:
        value = AWARENESS_PROMPT + """
User Principles 是可修订的准则摘要索引，包含朝汐整理的内容，不等于用户原话或用户确认。实际参考一般先 read_decision_context sources=["user_archive"] 查询 archive/user 原文；user_principles 也优先返回原文。原文与摘要冲突时以当前用户明确表达和原文为准。读到值得复用的原则时，可用 write_user_principle 自己抽象总结、补充或修订对应索引，引用实际读取的 source_ref 和逐字 source_quote，保留条件和例外；不必每轮写，不修改原始 archive。Decision Journal 是你从真实选择和反馈中总结的暂时判断，可参考，不是用户原话或硬规则。Choice History 只作弱证据。当前现实和明确表达优先。需要时 read_decision_context sources 可选 user_principles/decision_journal；不全量预读。
反馈是同一主回复的旁产物：用户明确承接下面某条选择且谈到实际结果时，必须在 awareness 中填 feedback={decision_id, user_final_choice:null或明确选择, outcome_label:GOOD/BAD/NEUTRAL/MIXED/NO_DIFFERENCE/UNKNOWN, outcome_text:本轮原话, feedback_source:natural或follow_up}。模糊的“挺好”“都一样”、不能唯一确认选择对象时不绑反馈；最终选择不明用 null，不臆造。反馈不直接变用户偏好。先简短自然回应，不在前台声称已经总结出长期经验；后台才反思。只是在接受已发生的结果时 mode=NONE，不把接受反馈改写成新的 ADVISE，也不能用一段安慰或新建议代替 feedback 字段。
awareness 可填 journal_ids（仅实际读取的日记 ID）、follow_up_policy:NEVER/PASSIVE/OPPORTUNISTIC/SCHEDULED、follow_up_after:含时区ISO时间或null。琐碎菜单 NEVER、饮料小消费 PASSIVE；值得回顾才 OPPORTUNISTIC，明确长期观察时间才 SCHEDULED。不能每个 PICK 都主动问。后台反思不写进本轮 reply schema。
"""
        if slim:
            value = (AWARENESS_PROMPT.splitlines()[-1] +
                '\n只提交本轮已有资料支持的决策或反馈，context_refs/principle_ids/journal_ids 仅填实际读取的 ID；'
                'mode=NONE 可以接受反馈，outcome_label/outcome_text/feedback_source 必须来自用户本轮真实反馈。')
        if unified:
            # Reply/control instructions are supplied once by the common runtime.
            value = "\n".join(line for line in value.splitlines()
                              if not line.startswith("最终回复必须输出 JSON"))
        if self.providers:
            value += "\n已注册按需扩展资料来源：" + ", ".join(self.providers)
        if candidates := self.feedback_candidates(conversation):
            value += "\n本轮反馈协议：若当前用户明确说候选中的哪个建议后来效果如何，最终 JSON 的 awareness.feedback 必须包含该 decision_id、outcome_label 与 outcome_text（原话）；只有自然回复不算保存反馈。如果对象不明确则 feedback=null，不猜。接受结果用 mode=NONE，但不能省掉 feedback。"
            value += "\n可承接反馈的近期选择（仅明确承接才记录，不猜对象；legacy_unabstracted 的 summary 是旧原文，不代表已经抽象的问题）：" + json.dumps(
                [{"decision_id": r["decision_id"], "summary": r.get("summary"), "suggestion": r.get("suggestion"),
                  "timestamp": r.get("timestamp"), "follow_up_status": r.get("follow_up_status"),
                  "decision_question": r.get("decision_question"), "question_status": r.get("question_status")} for r in candidates], ensure_ascii=False)
        try:
            if private_owner() and self.follow_up and self.follow_up.policy_allowed() and self.follow_up.budget_allowed():
                ready = self.follow_up.candidates(scope=choice_scope(), opportunistic=True)
                if ready:
                    value += "\n可顺便回访（仅在当前聊天自然合适时问，不抢占用户问题；问后填 awareness.follow_up_asked_id）：" + json.dumps(
                        {"decision_id": ready[0]['decision_id'], "summary": ready[0]['summary']}, ensure_ascii=False)
        except (OSError, ValueError, TypeError):
            logger.warning('optional follow-up context unavailable')
        return value

    def commit(self, trace: DecisionAwarenessTrace | None, error: str | None, conversation, builder) -> dict | None:
        from zhaoxi.cognitive_stream.turn import current_turn
        turn = current_turn()
        if not private_owner():
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
        commit_errors = []
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
        valid_principles = {ref.split(":", 1)[1] for ref in
            [*available.get("principles", []), *available.get("user_principles", [])]
            if ref.startswith(("principles:", "user_principles:"))}
        valid_journal = {ref.removeprefix("decision_journal:") for ref in available.get("decision_journal", [])}
        trace.journal_ids = [i for i in trace.journal_ids if i in valid_journal]
        trace.principle_ids = [identity for identity in trace.principle_ids if identity in valid_principles]
        trace.guard_flags = list(dict.fromkeys(guard_flags))
        scope = choice_scope()
        if trace.feedback:
            candidates = self.feedback_candidates(conversation)
            known = {r["decision_id"] for r in candidates}
            known.update(ref.removeprefix("choice_history:") for ref in available.get("choice_history", []))
            if self.history and trace.feedback.decision_id in known:
                try:
                    self.history.feedback(scope=scope, final=trace.feedback.user_final_choice,
                        decision_id=trace.feedback.decision_id, overridden=trace.feedback.overridden,
                        outcome=trace.feedback.outcome, outcome_label=trace.feedback.outcome_label,
                        outcome_text=trace.feedback.outcome_text, feedback_source=trace.feedback.feedback_source,
                        source_message_id=user.message_id)
                except (ValueError, OSError) as exc:
                    commit_errors.append("feedback_storage_failed")
                    logger.warning("choice feedback not saved: %s", type(exc).__name__)
            else:
                commit_errors.append("feedback_target_unknown")
                trace.feedback = None
        if trace.follow_up_asked_id:
            ready = self.follow_up.candidates(scope=scope, opportunistic=True) if self.follow_up else []
            if self.follow_up and self.follow_up.policy_allowed() and self.follow_up.budget_allowed() and any(r['decision_id'] == trace.follow_up_asked_id for r in ready):
                try:
                    self.history.event(trace.follow_up_asked_id, 'follow_up', scope=scope,
                        follow_up_status='ASKED', asked_at=datetime.now(UTC).isoformat())
                except OSError:
                    commit_errors.append("follow_up_storage_failed")
                    logger.warning('opportunistic follow-up receipt unavailable')
            else:
                trace.follow_up_asked_id = None
        issue = question_issue(trace, user.content or "")
        identity = uuid5(NAMESPACE_URL, "choice:" + scope + ":" + user.message_id).hex
        existing = (self.history.get(identity, scope=scope) or next(
            (item for item in self.history.list(limit=1000, scope=scope)
             if item.get("source_message_id") == user.message_id), None)) if issue is None and self.history else None
        row = {**trace.model_dump(mode="json"), "decision_id": existing["decision_id"] if existing else identity,
               "scope": scope, "timestamp": datetime.now(UTC).isoformat(),
               "summary": trace.decision_question or "", "suggestion": trace.agent_recommendation,
               "registration_status": issue or "recordable", "commit_errors": commit_errors}
        if issue is None and self.history:
            try:
                self.history.record(row["decision_id"], trace, scope=scope,
                                    source_text=user.content or "", source_message_id=user.message_id)
                row["registration_status"] = "recorded"
            except (OSError, ValueError) as exc:
                row["registration_status"] = "storage_failed"
                logger.warning("choice history not saved: %s", type(exc).__name__)
        elif issue is None:
            row["registration_status"] = "storage_failed"
            commit_errors.append("choice_storage_unavailable")
        rejected = issue is not None and trace.mode is not DecisionMode.NONE and trace.decision_kind == "NEW"
        if rejected:
            logger.warning("choice not registered: %s", issue)
        self.recent_traces.append(row)
        self.recent_traces[:] = self.recent_traces[-20:]
        from zhaoxi.observability import current_trace
        if runtime := current_trace():
            if commit_errors or rejected or row["registration_status"] == "storage_failed":
                runtime.terminal_status = "partial"
                runtime.emit("decision_commit_failed", "decision", "failed", "正文已保留，决策或反馈未完成保存",
                             error_code=commit_errors[0] if commit_errors else row["registration_status"])
            runtime.decision_used = trace.mode is not DecisionMode.NONE
            runtime.emit("decision_awareness", "decision", "warning" if rejected or row["registration_status"] == "storage_failed" else "success",
                         "问题摘要未通过登记校验" if rejected else "已形成生活判断",
                         metadata=row)
        return row

    def diagnostics(self) -> dict:
        return {"decision_mode": "agency", "latest": self.recent_traces[-1] if self.recent_traces else None,
                "recent": list(self.recent_traces),
                "choice_history": self.history.list() if self.history else [],
                "context_providers": list(self.providers)}
