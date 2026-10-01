"""Request-local limits and factual outcomes, independent of observability."""
from dataclasses import dataclass, field
from difflib import SequenceMatcher
import hashlib
import json
import re

CONTROLS = {"request_tool_group", "inspect_tool_catalog", "emit_interim_reply"}


def argument_shape(value):
    if isinstance(value, dict):
        return {key: argument_shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return sorted({json.dumps(argument_shape(item), sort_keys=True) for item in value})
    return type(value).__name__


def failure_fingerprint(name, arguments, result):
    error = str(result.error or "tool_failure")
    code = str(result.metadata.get("error_code") or result.metadata.get("result_code") or
               (error if re.fullmatch(r"[a-zA-Z_.-]{1,80}", error) else "tool_failure"))
    normalized = re.sub(r"(?:0x)?[0-9a-f]{8,}|\d+", "#", error.casefold())
    normalized = re.sub(r"(['\"]).*?\1", "<value>", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()[:500]
    value = [name, code, normalized, argument_shape(arguments)]
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def normalized_query(value):
    text = re.sub(r"[\s，。！？、,.!?]+", "", str(value).casefold())
    return re.sub(r"帮我|请|一下|查询|检索|搜索|查找|回忆|的", "", text)


@dataclass
class LoopSafety:
    model_limit: int = 3
    tool_limit: int = 2
    repair_limit: int = 1
    model_round: int = 0
    tool_round: int = 0
    repair_round: int = 0
    failed_tools: dict = field(default_factory=dict)
    fingerprints: dict = field(default_factory=dict)
    locked: set = field(default_factory=set)
    outcomes: list = field(default_factory=list)
    search_cache: list = field(default_factory=list)
    seen_results: set = field(default_factory=set)
    no_progress: int = 0
    progress: bool = False
    forced_reason: str = ""
    last_fingerprint: str | None = None
    last_retry: int = 0

    def begin_round(self):
        self.model_round += 1
        self.progress = False

    def finish_round(self):
        self.no_progress = 0 if self.progress else self.no_progress + 1
        if self.no_progress >= 2:
            self.force("no_progress")

    def force(self, reason):
        if not self.forced_reason:
            self.forced_reason = reason

    def observe_control(self, call, result):
        if result.success:
            key=(call.name,json.dumps(result.data,sort_keys=True,ensure_ascii=False,default=str))
            self.progress=self.progress or key not in self.seen_results
            self.seen_results.add(key)

    def cached_search(self, call):
        if call.name != "search_memories":
            return None
        query = normalized_query(call.arguments.get("query", ""))
        filters = {key: value for key, value in call.arguments.items() if key != "query"}
        for previous, options, result in self.search_cache:
            if options == filters and (query == previous or query and previous and
                    SequenceMatcher(None, query, previous).ratio() >= .9):
                return result.model_copy(deep=True)
        return None

    def observe(self, call, result, *, mutation=False):
        self.outcomes.append((call.name, result.model_copy(deep=True)))
        fingerprint = None
        retry = 0
        if result.success:
            for name, previous in reversed(self.outcomes[:-1]):
                if name==call.name and previous.error=="tool_validation_error":
                    previous.metadata["resolved_by_retry"]=True
                    break
            key = (call.name, json.dumps(result.data if result.data is not None else result.content,
                                        sort_keys=True, ensure_ascii=False, default=str))
            self.progress = self.progress or mutation or key not in self.seen_results
            self.seen_results.add(key)
        else:
            fingerprint = failure_fingerprint(call.name, call.arguments, result)
            self.fingerprints[fingerprint] = self.fingerprints.get(fingerprint, 0) + 1
            retry = self.fingerprints[fingerprint] - 1
            self.last_fingerprint, self.last_retry = fingerprint, retry
            self.failed_tools[call.name] = self.failed_tools.get(call.name, 0) + 1
            # Unknown writes, denied permission and execution ambiguity are not
            # safe parameter repairs. They must not be replayed automatically.
            unsafe = result.metadata.get("unknown_outcome") or result.error == "permission_denied"
            if unsafe or retry >= 1 or self.failed_tools[call.name] >= 2:
                self.locked.add(call.name)
                self.force("tool_failure_limit")
        if call.name == "search_memories":
            self.search_cache.append((normalized_query(call.arguments.get("query", "")),
                {key: value for key, value in call.arguments.items() if key != "query"}, result.model_copy(deep=True)))
        return {"tool_failure_fingerprint": fingerprint, "tool_retry_count": retry,
                "tool_locked": call.name in self.locked}

    def metrics(self):
        return {"standard_model_round": self.model_round, "standard_tool_round": self.tool_round,
                "repair_round": self.repair_round, "forced_finalization_reason": self.forced_reason or None,
                "partial_success": any(r.success for _, r in self.outcomes) and
                    any(not r.success and not r.metadata.get("resolved_by_retry") for _, r in self.outcomes),
                "tool_locked": sorted(self.locked), "tool_failure_fingerprint":self.last_fingerprint,
                "tool_retry_count":self.last_retry}

    def fallback(self):
        completed, failed, unknown, skipped = {}, {}, {}, {}
        for name, result in self.outcomes:
            if result.metadata.get("resolved_by_retry"):
                continue
            target = skipped if result.metadata.get("not_executed") else unknown if result.metadata.get("unknown_outcome") else completed if result.success else failed
            target[name] = target.get(name, 0) + 1
        lines = ["本轮已停止继续处理。"]
        from zhaoxi.tools.metadata import TOOL_LABELS
        for label, values in (("已完成", completed), ("未完成", failed), ("未执行", skipped), ("结果未知", unknown)):
            if values:
                lines += ["", label + "："]
                lines += [f"- {TOOL_LABELS.get(name, name)} ×{count}" for name, count in values.items()]
        if not self.outcomes:
            lines += ["尚未完成任何工具操作。"]
        elif completed:
            lines += ["", "已完成的操作会保留；未完成或结果未知的部分没有算作完成。"]
        return "\n".join(lines)
