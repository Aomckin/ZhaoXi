"""Fast Gate 2.0: local confidence voting, with ambiguity delegated to Router."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import re
from collections.abc import Sequence

from zhaoxi.config.fast_gate import FastGateConfig
from zhaoxi.tools.manifest import is_action_request


class FastGateLane(StrEnum):
    FAST_CONFIDENT = "FAST_CONFIDENT"
    AMBIGUOUS = "AMBIGUOUS"
    HEAVY_CONFIDENT = "HEAVY_CONFIDENT"


@dataclass(frozen=True, slots=True)
class FastGateSignals:
    conversation_likeness: float = 0
    recent_context_relevance: float = 0
    recent_context_sufficient: bool = False
    current_cognition_relevance: float = 0
    current_cognition_sufficient: bool = False
    continuation_confidence: float = 0
    capability_match: float = 0
    resource_reference_confidence: float = 0
    historical_specificity: float = 0
    action_side_effect_confidence: float = 0
    decision_complexity: float = 0
    has_image: bool = False
    pending_permission: bool = False
    capability_groups: tuple[str, ...] = ()
    signal_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FastDialogueDecision:
    lane: FastGateLane
    reason: str
    signals: FastGateSignals = field(default_factory=FastGateSignals)
    fast_score: float = 0
    heavy_score: float = 0
    fast_positive_evidence: tuple[str, ...] = ()
    heavy_evidence: tuple[str, ...] = ()
    known_route: str | None = None

    @property
    def eligible(self) -> bool:
        return self.lane is FastGateLane.FAST_CONFIDENT

    @property
    def continuation_detected(self) -> bool:
        return self.signals.continuation_confidence > 0

    def diagnostics(self) -> dict:
        return {"fast_gate_version": 2, "fast_gate_decision": self.lane.value,
                "fast_gate_reason": self.reason, "fast_gate_signals": asdict(self.signals),
                "fast_score": self.fast_score, "heavy_score": self.heavy_score,
                "fast_positive_evidence": list(self.fast_positive_evidence),
                "heavy_evidence": list(self.heavy_evidence)}


def _terms(text: str) -> set[str]:
    # Local lexical overlap is evidence of relevance, never evidence of truth.
    ignored = {"最近", "近期", "现在", "这个", "那个", "一下", "我们", "你们", "什么", "自己"}
    terms = set(re.findall(r"[a-z][a-z0-9_]{2,}", text.casefold()))
    terms.update(part[i:i+2] for part in re.findall(r"[\u4e00-\u9fff]{2,}", text)
                 for i in range(len(part)-1) if part[i:i+2] not in ignored)
    return terms


def _relevance(text: str, context: str) -> float:
    query = _terms(text)
    overlap = query & _terms(context)
    return min(1.0, len(overlap) / min(4, len(query))) if query else 0


class FastDialogueGate:
    """Consume bounded local evidence; never call a model, Memory or a Tool."""

    def __init__(self, config: FastGateConfig | None = None) -> None:
        self.config = config or FastGateConfig()

    def collect(self, user_message: str, *, recent_context: str = "",
                current_cognition: str = "", current_topics: Sequence[str] = (), capability_groups: Sequence[str] = (),
                resource_refs: Sequence[str] = (), images: list[str] | None = None,
                pending_permission: bool = False, signal_errors: Sequence[str] = ()) -> FastGateSignals:
        text = " ".join(user_message.casefold().strip().split())
        # These are sentence shapes, not tool-name/domain exclusion lists.
        command = is_action_request(text) or bool(re.search(
            r"(?:帮我|替我|麻烦|自己去|(?:^|[，,；;])(?:请|去|先|再)|把.{1,40}(?:起来|进去|进|掉|成|到))"
            r"|^(?:读取|打开|查询|检索|计算|记录|保存|修改|删除).+"
            r"|(?:记|记录|保存|修改|删除|忘|提醒|补)(?:住|一下|起来|一份|掉|我)", text))
        mutation = bool(re.search(r"记|写|补|存|改|删|发|传|建|移|执行|同步|提醒|忘", text))
        opinion = bool(re.search(r"觉得|感觉|看着|看起来|有点|太.{1,8}了|真.{1,10}|好怪|舒服|烦|开心|累|哈哈|嘿嘿", text))
        question = bool(re.search(r"哪些|哪[个里天]|多少|什么时候|具体|什么|怎么|几[点号]|实时|最新|想(?:知道|了解|确认)|告诉我", text))
        greeting = bool(re.fullmatch(r"(?:小金毛|朝汐|暗苟|在吗|在不在|你好|嗨|晚安|早安|哈哈+|嘿嘿+)[？?！!。~～]*", text))
        personal_statement = (bool(re.match(r"(?:我|今天|最近|这几天).+", text)) and not question
            and not re.search(r"^(?:我|今天|最近|这几天).{0,8}(?:想|要|需要|希望|请求|准备|打算)", text))
        reaction = bool(re.match(r"(?:确实|是啊|对啊|嗯|好吧|这样|这也|那就).+", text)) and not command
        conversation = 0.95 if greeting else 0.9 if opinion and not command else 0.8 if personal_statement and not command else 0.8 if reaction else 0.2

        deictic = bool(re.search(r"(?:刚刚|刚才|之前|前面|上一).{0,8}(?:那个|那[两几]条|这|继续)|(?:这|那)[个份两条]|继续|接着|去补", text))
        pending_action = bool(re.search(r"缺.{0,16}(?:记录|文件|一份)|(?:还没|未完成|待处理|正在|需要).{0,24}(?:补|写|查|处理|执行|记录|文件)", recent_context))
        unresolved_reference = bool(re.search(r"(?:刚刚|刚才|之前|前面|上一).{0,8}(?:那个|那[两几]条|继续)|^(?:这个|那个|这份|那份)(?:你|它|呢|怎么样|如何|行吗|继续|$)", text))
        continuation = 0.95 if deictic and pending_action and command else 0.85 if deictic and pending_action and not opinion else 0.5 if deictic and (command or unresolved_reference) else 0
        side_effect = 0.95 if command and mutation else 0.9 if command and re.search(r"查|搜|读|获取|打开|算", text) else 0
        historical = 0.95 if re.search(r"上次|以前|之前|当时|去年|那次", text) and re.search(r"具体|哪些|什么|多少|什么时候|怎么说|说过|记得", text) else 0
        artifact = bool(re.search(r"[\w./\\-]+\.(?:md|pdf|docx?|txt|json|ya?ml|xlsx?|pptx?)\b|readme|\d+(?:\.\d+)+\s*版|(?:这|那|某)[份个条].{0,12}(?:计划|任务书|记录|文档|提交)|(?:仓库|书馆|书库).{0,16}(?:里|中|内容|提交)", text))
        artifact = artifact or any(ref.casefold() in text for ref in resource_refs if ref)
        access = command or question or bool(re.search(r"内容|写了|里面|写的", text))
        resource = 0.95 if artifact and access else 0.4 if artifact and not opinion else 0
        multi_step = len(re.findall(r"(?:^|[，,；;])(?:先|然后|再|最后)", text)) >= 2
        choice = bool(re.search(r"要不要|该不该|选哪个|值不值得|去不去|接不接|怎么选"
            r"|(?:还是|或者).{0,30}[？?吗]$|(?:选|应该|该|推荐).{0,40}(?:还是|或者)", text))
        complexity = 0.95 if multi_step else 0.85 if choice else 0
        groups = tuple(dict.fromkeys(capability_groups))
        capability = 0.9 if groups and (command or question) and not (opinion and not command) else 0.15 if groups else 0
        recent_relevance = _relevance(text, recent_context)
        if reaction and recent_context:
            recent_relevance = max(recent_relevance, 0.85)
        cognition_relevance = _relevance(text, current_cognition)
        if any(topic.casefold() in text for topic in current_topics if len(topic) >= 2):
            cognition_relevance = max(cognition_relevance, 0.9)
        risks = max(side_effect, historical, resource, capability, complexity)
        short_answer = risks <= self.config.risk_ceiling and not (deictic and not recent_context)
        recent_sufficient = bool(recent_context) and recent_relevance >= self.config.sufficiency_threshold and short_answer and (conversation >= self.config.conversation_threshold or opinion)
        cognition_sufficient = bool(current_cognition) and cognition_relevance >= self.config.relevance_threshold and short_answer and not question and not command
        return FastGateSignals(conversation, recent_relevance, recent_sufficient,
            cognition_relevance, cognition_sufficient, continuation, capability, resource,
            historical, side_effect, complexity, bool(images), pending_permission, groups,
            tuple(signal_errors))

    def decide(self, user_message: str, **context) -> FastDialogueDecision:
        s = self.collect(user_message, **context)
        c = self.config
        heavy_values = {"capability_match": s.capability_match,
            "resource_reference_confidence": s.resource_reference_confidence,
            "historical_specificity": s.historical_specificity,
            "action_side_effect_confidence": s.action_side_effect_confidence,
            "decision_complexity": s.decision_complexity,
            "continuation_confidence": s.continuation_confidence}
        heavy = tuple(name for name, value in heavy_values.items() if value >= c.strong_threshold)
        if s.has_image:
            heavy += ("has_image",)
        if s.pending_permission:
            heavy += ("pending_permission",)
        positive = tuple(name for name, value in {
            "conversation_likeness": s.conversation_likeness >= c.conversation_threshold,
            "recent_context_sufficient": s.recent_context_sufficient,
            "current_cognition_sufficient": s.current_cognition_sufficient,
            "low_capability_match": s.capability_match <= c.risk_ceiling,
            "low_resource_reference": s.resource_reference_confidence <= c.risk_ceiling,
            "low_historical_specificity": s.historical_specificity <= c.risk_ceiling,
            "low_action_side_effect": s.action_side_effect_confidence <= c.risk_ceiling,
        }.items() if value)
        fast_score = max(s.conversation_likeness,
                         s.recent_context_relevance if s.recent_context_sufficient else 0,
                         s.current_cognition_relevance if s.current_cognition_sufficient else 0)
        heavy_score = max(*heavy_values.values(), float(s.has_image), float(s.pending_permission))
        known_route = None
        if heavy:
            if s.decision_complexity >= c.strong_threshold:
                known_route = "plan" if multi_step_request(user_message) else None
            elif not s.pending_permission:
                known_route = "tool"
            return FastDialogueDecision(FastGateLane.HEAVY_CONFIDENT, heavy[0], s,
                round(fast_score, 3), round(heavy_score, 3), positive, heavy, known_route)
        sufficient = s.recent_context_sufficient or s.current_cognition_sufficient or s.conversation_likeness >= c.conversation_threshold
        # Missing/conflicting context never becomes FAST just because no risk was found.
        uncertain = s.signal_errors or (s.continuation_confidence > c.risk_ceiling and not s.recent_context_sufficient) or heavy_score > c.risk_ceiling
        lane = FastGateLane.FAST_CONFIDENT if user_message.strip() and sufficient and not uncertain and fast_score >= c.fast_min_score and len(positive) >= c.fast_min_positive_votes else FastGateLane.AMBIGUOUS
        reason = "safe_conversation" if lane is FastGateLane.FAST_CONFIDENT else "insufficient_or_conflicting_evidence"
        return FastDialogueDecision(lane, reason, s, round(fast_score, 3), round(heavy_score, 3), positive, heavy)


def multi_step_request(text: str) -> bool:
    return len(re.findall(r"(?:^|[，,；;])(?:先|然后|再|最后)", text)) >= 2
