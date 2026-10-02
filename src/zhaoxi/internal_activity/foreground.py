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
            return await method(self, item, *args, **kwargs)
        finally:
            if runtime and direct:
                runtime.foreground_exit()
    return wrapped
