"""Deterministic human-readable receipts; no additional model calls."""
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from uuid import uuid4
STATUS_LABELS = {"QUEUED": "已排队", "RUNNING": "正在执行", "SUCCESS": "已完成", "NO_CHANGE": "无变化", "SKIPPED": "已跳过", "BLOCKED": "未执行", "FAILED": "执行失败", "CANCELLED": "已中止"}
REASONS = {"disabled": "此活动当前关闭。", "runtime_disabled": "内部活动总开关已关闭。", "manual_only": "此状态仅允许手动执行。", "foreground": "正在处理前台对话，后台活动已让路。", "foreground_preemption": "收到新的前台消息，后台活动已让路。", "cooldown": "距离上次执行太近，仍在等待间隔。", "backoff": "连续失败后正在等待重试。", "daily_budget": "此活动的今日预算已用尽。", "budget": "本次或今日资源预算不足。", "maintenance_pending": "优先处理待完成的维护任务。", "clean": "没有需要处理的内容。", "candidate_error": "检查待处理内容失败，可稍后重试。", "busy": "已有后台活动正在执行。", "social_write_confirmation": "群聊发言需要本次明确确认。"}
def reason_text(reason):
    if str(reason).startswith("presence:"):
        return "当前生活状态不允许此活动。"
    return REASONS.get(reason, "活动未执行，具体原因请查看技术详情。")
@dataclass
class ActionReceipt:
    action_id: str = field(default_factory=lambda: uuid4().hex)
    activity_name: str = ""
    title: str = ""
    phase: str = "FINISHED"
    status: str = "NO_CHANGE"
    changed: bool = False
    summary: str = ""
    details: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    side_effects: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    error: dict | None = None
    started_at: str = ""
    finished_at: str | None = None
    duration_ms: float = 0
    raw_payload: dict = field(default_factory=dict)
    trigger: str = "AUTO"
    presence: str = ""
    cost_class: str = ""
    def diagnostics(self):
        return {**asdict(self), "status_label": STATUS_LABELS[self.status]}
def build_receipt(spec, *, result=None, status=None, reason=None, started_at=None, trigger="AUTO", presence="", action_id=None):
    now = datetime.now(UTC)
    raw = result.diagnostics() if result else {}
    original = raw.get("status", "NO_CHANGE")
    status = status or ({"PREEMPTED": "CANCELLED", "SKIP": "SKIPPED", "NO_MESSAGE": "NO_CHANGE", "FAILED": "FAILED", "REJECTED": "FAILED"}.get(original) or ("SUCCESS" if raw.get("changed") or raw.get("message_sent") else "NO_CHANGE"))
    summary = (reason_text(reason) if reason else raw.get("summary")) or {"RUNNING": "正在执行，请稍候。", "SUCCESS": "活动已完成。", "NO_CHANGE": "检查完成，没有需要调整的内容，本次未产生业务变化。", "FAILED": "活动执行失败，可稍后重试；请查看失败阶段。", "CANCELLED": "后台活动已中止并让路给前台对话。", "SKIPPED": "没有需要处理的内容。", "BLOCKED": "当前条件不允许执行。"}.get(status, "等待执行。")
    summary = {"RELATED_TO": "重温旧记忆，建立了新的关联。", "Cognition signal": "已更新近期认知趋势。"}.get(summary, summary)
    if summary in {"LURK","LEAVE","CHAT","REACT","group_cooldown_or_whitelist","manual_write_confirmation_required","repeated_topic","write_gate_changed","source_unavailable"}:
        summary = {"LURK": "围观了授权群消息，没有发言。", "LEAVE": "没有合适的公开话题，已安静离开。", "CHAT": "已在授权群发言。", "REACT": "已对公开话题回应。", "group_cooldown_or_whitelist": "没有可用的授权群，或仍在等待每群间隔。", "manual_write_confirmation_required": "本次没有确认群聊发言，未发送消息。", "repeated_topic": "话题重复，保持安静。", "write_gate_changed": "发言前权限、状态或预算已变化，未发送消息。", "source_unavailable": "群聊插件不可用，未发送消息。"}[summary]
    elif summary.startswith("privacy_gate_reject:"):
        status, summary = "BLOCKED", "隐私检查拒绝这次发言，未发送消息。"
    elif summary.startswith("send_failed:"):
        status, summary = "FAILED", "外部消息发送失败，需要核对插件投递状态。"
    start = started_at or now
    receipt = ActionReceipt(activity_name=spec.name, title=spec.label + " · " + STATUS_LABELS[status], phase="RUNNING" if status == "RUNNING" else "FINISHED", status=status, changed=bool(raw.get("changed")), summary=summary, details=raw.get("details",[]), warnings=raw.get("warnings",[]), metrics=raw.get("cost", {}), side_effects={"message_sent": bool(raw.get("message_sent")), "external_io": bool(spec.requires_external_io and status not in {"BLOCKED","SKIPPED"}), "external_write": bool(raw.get("message_sent") and spec.can_message_external), "external_write_unknown": bool(status == "FAILED" and spec.can_message_external)}, started_at=start.isoformat(), finished_at=None if status == "RUNNING" else now.isoformat(), duration_ms=round((now-start).total_seconds()*1000, 2), raw_payload={**raw, **({"reason": reason} if reason else {})}, trigger=trigger, presence=presence, cost_class=spec.cost_class.value)
    if action_id:
        receipt.action_id = action_id
    if status == "FAILED":
        receipt.error = {"stage": "candidate_check" if reason == "candidate_error" else "execution", "retryable": True}
    return receipt
