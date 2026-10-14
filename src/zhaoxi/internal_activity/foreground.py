"""Preempt cancellable internal work at foreground ingress."""
from functools import wraps
from datetime import UTC, datetime


def foreground_activity(method):
    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        runtime = getattr(self.agent, "internal_activity", None)
        if runtime:
            runtime.foreground_enter()
        try:
            return await method(self, *args, **kwargs)
        finally:
            if runtime:
                runtime.foreground_exit()
    return wrapped


def external_foreground(method):
    @wraps(method)
    async def wrapped(self, item, *args, **kwargs):
        from zhaoxi.perception.router import route
        from zhaoxi.perception.models import AttentionHint
        runtime = getattr(self.agent, "internal_activity", None)
        direct = route(item) == AttentionHint.DIRECT
        if runtime and direct:
            runtime.foreground_enter()
            state = getattr(self.agent, "proactive_state", None)
            if state and item.actor_role == "OWNER":
                state.interaction.interact(datetime.now(UTC))
        try:
            if direct and getattr(self.settings, "unified_reply_enabled", False):
                from zhaoxi.reliability import CorrelationContext, correlation_scope, provider_budget_scope
                from zhaoxi.observability import action_trace_scope
                identity = "external:" + item.observation_id
                with correlation_scope(CorrelationContext(trace_id=identity, request_id=identity)), provider_budget_scope(
                        self.settings.request_max_model_calls, self.settings.request_max_total_tokens,
                        policy=self.settings.request_budget_policy), action_trace_scope() as trace:
                    trace.build_id = getattr(self.agent, "build_id", None)
                    trace.unified_reply = getattr(self.agent, "decision_mode", "legacy") == "agency"
                    trace.channel = item.source
                    trace.configuration_id = getattr(self.agent, "reply_profile_id", None)
                    trace.request_timeout_seconds = self.agent.timeout_seconds
                    trace.has_images = any(part.type == "image" for part in item.effective_parts)
                    trace.route_source = "unified_channel"
                    trace.runtime_lane = "standard"
                    trace.emit("request_started", "request", "running", "已收到定向请求")
                    try:
                        result = await method(self, item, *args, **kwargs)
                        if result is None and trace.result_status != "duplicate":
                            trace.response_status = "failed"
                        return result
                    except BaseException:
                        trace.response_status = "failed"
                        raise
                    finally:
                        trace.finish()
            return await method(self, item, *args, **kwargs)
        finally:
            if runtime and direct:
                runtime.foreground_exit()
    return wrapped
