"""Short-lived conversation state."""

from zhaoxi.core.message import Message, Role


class Conversation:
    """Hold and trim messages for one in-memory conversation."""

    def __init__(self, messages: list[Message] | None = None, max_messages: int = 40) -> None:
        self._messages = list(messages or [])
        self.max_messages = max_messages

    @property
    def messages(self) -> list[Message]:
        return list(self._messages)

    def add(self, message: Message) -> Message:
        self._messages.append(message)
        self._trim()
        return message

    def add_delivery(self, message: Message) -> None:
        if any(item.delivery_id == message.delivery_id for item in self._messages):
            return
        index = next((i for i, item in enumerate(self._messages) if item.timestamp > message.timestamp), len(self._messages))
        self._messages.insert(index, message)
        self._trim()

    def add_user(self, content: str, *, images: list[str] | None = None) -> Message:
        return self.add(Message(role=Role.USER, content=content, images=images or []))

    def add_assistant(self, content: str | None, **kwargs: object) -> Message:
        return self.add(Message(role=Role.ASSISTANT, content=content, **kwargs))

    def add_tool(self, content: str, *, tool_call_id: str, name: str) -> Message:
        return self.add(Message(role=Role.TOOL, content=content, tool_call_id=tool_call_id, name=name))

    def recent(self, limit: int | None = None) -> list[Message]:
        size = limit or self.max_messages
        return self.messages[-size:]

    def clear(self) -> None:
        self._messages.clear()

    def _trim(self) -> None:
        overflow = len(self._messages) - self.max_messages
        if overflow > 0:
            del self._messages[:overflow]

