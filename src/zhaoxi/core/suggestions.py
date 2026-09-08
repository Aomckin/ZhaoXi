"""Four bounded suggestions, piggybacked on existing replies with local fallback."""
import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from zhaoxi.core.message import strip_echoed_timeline_header


SUGGESTION_RULE = (
    '\n最终自然回复后可以附加 <quick_suggestions>{"chat":"聊天类建议",'
    '"action":"行动类建议","life":"当前生活相关建议","explore":"另一条不同建议"}</quick_suggestions>。'
    '每条是不超过50字的用户可直接发送的话，结合当前对话，不泄露内部事件和调试字段。工具调用时不附加。'
)


class QuickSuggestions:
    def __init__(self, timezone="Asia/Shanghai", refresh_minutes=180):
        self.timezone = ZoneInfo(timezone)
        self.refresh_interval = timedelta(minutes=refresh_minutes)
        self.generated_at = None
        self.suggestions = []
        self.source_context = "fallback"
        self._key = None
        self.generated = 0

    def accept(self, values, now=None):
        if not isinstance(values, dict) or set(values) != {"chat", "action", "life", "explore"}:
            return False
        items = [values[k].strip() if isinstance(values[k], str) else "" for k in ("chat", "action", "life", "explore")]
        if (len(set(items)) != 4 or any(not s or len(s) > 80 or '\n' in s or
                any(token in s for token in ('delivery_id', 'event_type', 'related_payload', '<', '>')) for s in items)):
            return False
        self.suggestions = items
        self.generated_at = now or datetime.now(UTC)
        self.source_context = "model"
        self._key = None
        self.generated += 1
        return True

    def extract(self, content):
        head, marker, tail = content.partition('<quick_suggestions>')
        if marker:
            payload, closing, _ = tail.partition('</quick_suggestions>')
            if closing:
                try:
                    self.accept(json.loads(payload))
                except (ValueError, TypeError):
                    pass
            return strip_echoed_timeline_header(head.rstrip())
        return strip_echoed_timeline_header(content)

    def get(self, conversation, state=None, focus=False, recent_proactive=False, now=None):
        now = now or datetime.now(UTC)
        local = now.astimezone(self.timezone)
        messages = conversation.messages
        recent = next((m for m in reversed(messages) if m.role.value == 'user'), None)
        mode = state.interaction.refresh(now).value if state else "IDLE"
        key = (local.date(), local.hour // 3, mode, focus, recent_proactive,
               recent.timestamp if recent else None)
        if self.suggestions and now - self.generated_at < self.refresh_interval:
            if self._key is None:
                self._key = key
            if self._key == key:
                return self.snapshot()
        text = recent.content if recent and recent.content else ''
        chat = '朝汐，接着刚才的话题聊聊吧。' if mode == 'ACTIVE' else '朝汐，陪我聊一会儿吧。'
        action = '帮我看看今天还有什么没收尾。' if local.hour >= 17 else '帮我看看今天最值得先做的一件事。'
        life = '看看我这段专注持续多久了。' if focus else '聊聊我今天的状态。'
        explore = '说说刚才那条提醒吧。' if recent_proactive else ('帮我把刚才的编程问题拆成下一步。' if any(k in text for k in ('代码', '编程', 'bug')) else '一起回顾一下今天的小进展吧。')
        if mode == 'SEMI_ACTIVE':
            chat = '我刚忙完，陪我放松一会儿吧。'
        if mode == 'AWAY':
            chat = '我回来啦，陪我慢慢找回状态吧。'
        self.suggestions = [chat, action, life, explore]
        self.generated_at, self._key, self.source_context = now, key, 'local_context'
        self.generated += 1
        return self.snapshot()

    def snapshot(self):
        return {'generated_at': self.generated_at, 'suggestions': list(self.suggestions),
                'source_context': self.source_context}
