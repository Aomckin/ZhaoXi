"""QQ expression policy and projection-session identity."""


class ChannelExpressionPolicy:
    @staticmethod
    def prompt(kind: str | None) -> str:
        if kind == "group":
            return "QQ 群聊：像自然聊天，普通闲聊优先 1~2 小段、20~120 中文字符；复杂问题可适当展开，避免占屏。用空行分自然消息段。"
        if kind == "private":
            return "QQ 私聊：自然简短，普通闲聊优先 1~4 小段、30~180 中文字符；复杂问题可更长。用空行分自然消息段，可使用 [emoji:属性]。"
        return ""


def session_key(item) -> str:
    return f"qq/{item.conversation_kind}/{item.conversation_id}"
