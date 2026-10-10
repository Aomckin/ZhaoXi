"""Save an image already present in the conversation into the emoji library."""

from pydantic import BaseModel, Field

from zhaoxi.core.conversation import Conversation
from zhaoxi.expression import EmojiManager, EmojiMetadata
from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.tools.base import Tool, ToolResult


class SaveEmojiInput(BaseModel):
    image_ref: str = Field(
        default="latest",
        min_length=1,
        max_length=160,
        description="模型上下文提供的 <conversation-image:消息ID:序号> 原图引用；latest 仅指当前输入的唯一图片，多图须 latest:0、latest:1。",
    )
    description: str = Field(min_length=2, max_length=2000)
    tags: list[str] = Field(min_length=1, max_length=50)
    emotion: str | None = Field(default=None, max_length=80)
    intensity: float | None = Field(default=None, ge=0, le=1)


class SaveEmojiTool(Tool):
    name = "save_emoji"
    description = (
        "仅当用户明确要求保存、收藏或收进表情包时，收藏当前会话中的图片。"
        "优先填写上下文的 <conversation-image:消息ID:序号>；latest 仅指当前输入唯一图，多图必须指明索引。历史 / 外部图按来源引用，不猜最新图；绝不能传本地路径。"
        "description 应描述表达含义和适用语境，而非只描述画面；tags 使用自然中文短词。"
        "可以结合用户说明与上下文，但用途不确定时不要过度脑补。失败或 duplicate 必须如实说明。"
    )
    input_model = SaveEmojiInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    group = "expression"
    persistent = True
    default_confirm_write = False

    def __init__(self, manager: EmojiManager, conversation: Conversation) -> None:
        self.manager = manager
        self.conversation = conversation

    def resource_scope(self, arguments: dict) -> str:
        return "emoji_library"

    def _resolve(self, image_ref: str) -> str | None:
        from zhaoxi.tools.execution_context import resolve_image_reference
        from zhaoxi.cognitive_stream.turn import current_turn
        if image_ref.startswith("<conversation-image:"):
            return resolve_image_reference(image_ref)
        turn = current_turn()
        reference, separator, raw_index = image_ref.rpartition(":")
        if separator and raw_index.isdigit():
            index = int(raw_index)
        else:
            reference, index = image_ref, 0
        if turn and reference in {"latest", turn.trigger_event.event_id}:
            images = list(turn.images)
            if not separator and len(images) != 1:
                return None
            return images[index] if index < len(images) and images[index].startswith("data:image/") else None
        if reference == "latest":
            from zhaoxi.core.message import Role
            candidates = [item for item in self.conversation.messages if item.role == Role.USER and item.images]
            if turn and len(candidates) != 1:
                return None
            message = candidates[-1] if candidates else None
            if message is not None and not separator and len(message.images) != 1:
                return None
        else:
            message = next((item for item in self.conversation.messages if item.message_id == reference), None)
        if message is None or index >= len(message.images):
            return None
        image = message.images[index]
        return image if image.startswith("data:image/") else None

    async def execute(self, arguments: SaveEmojiInput) -> ToolResult:
        image = self._resolve(arguments.image_ref)
        if image is None:
            return ToolResult(success=False, content="图片引用缺失或有歧义，请按来源和图片序号重新选择。", error="image_reference_unresolved", data={"status": "not_found", "image_ref": arguments.image_ref})
        result = self.manager.add_data_url(image, EmojiMetadata(
            description=arguments.description,
            tags=arguments.tags,
            emotion=arguments.emotion,
            intensity=arguments.intensity,
        ))
        content = {
            "added": "表情已经收藏并立即加入可用图库。",
            "duplicate": "这张图已经在表情柜里了，没有重复保存。",
        }.get(result.status, "表情收藏没有完成。")
        return ToolResult(success=True, content=content, data=result.model_dump(mode="json"))
