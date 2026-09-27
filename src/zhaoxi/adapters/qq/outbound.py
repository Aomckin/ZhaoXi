"""Send planned QQ text and emoji segments in order."""
import asyncio
import base64
import random
import re

from zhaoxi.core.reply.parser import parse_reply
from zhaoxi.config.external_timing import load_external_timing


def _segments(content: str, emoji_service=None):
    result = []
    for part in parse_reply(content).segments:
        if part.type == "text":
            result.extend({"type": "text", "data": {"text": text.strip()}}
                          for text in re.split(r"\n\s*\n+", part.content) if text.strip())
        elif emoji_service is not None:
            match = emoji_service.resolve_tags(part.requested_tags)
            if match and match.status == "matched" and match.emoji_id:
                path = emoji_service.image_path(match.emoji_id)
                if path and path.stat().st_size <= 10_485_760:
                    mime = "image/gif" if path.suffix.lower() == ".gif" else (
                        "image/png" if path.suffix.lower() == ".png" else "image/jpeg")
                    payload = base64.b64encode(path.read_bytes()).decode("ascii")
                    result.append({"type": "image", "data": {
                        "file": f"base64://{payload}"}})
    return result


def _bounded(segments: list[dict], maximum: int) -> list[dict]:
    if len(segments) <= maximum:
        return segments
    # Preserve every word and image while reducing only the number of messages.
    while len(segments) > maximum:
        pair = next((i for i in range(len(segments)-1)
                     if segments[i]["type"] == segments[i+1]["type"] == "text"), None)
        if pair is None:
            break
        segments[pair]["data"]["text"] += "\n" + segments[pair+1]["data"]["text"]
        del segments[pair+1]
    return segments


async def send_reply(transport, observation, content: str, *, settings=None,
                     emoji_service=None) -> int:
    kind = observation.conversation_kind
    if kind == "group":
        params = {"group_id": int(observation.conversation_id)}
        action = "send_group_msg"
        maximum = getattr(settings, "qq_group_reply_max_segments", 3)
    elif kind == "private":
        params = {"user_id": int(observation.actor_id)}
        action = "send_private_msg"
        maximum = getattr(settings, "qq_private_reply_max_segments", 4)
    else:
        raise ValueError("unsupported conversation")
    segments = _bounded(_segments(content, emoji_service), maximum)
    if not segments:
        raise ValueError("empty QQ reply")
    lower = getattr(settings, "qq_reply_segment_delay_min_ms", 300)
    upper = max(lower, getattr(settings, "qq_reply_segment_delay_max_ms", 800))
    if settings is not None:
        interval = load_external_timing(settings.interface_settings_path).reply_interval_seconds
        if interval is not None:
            lower = upper = round(interval * 1000)
    for index, segment in enumerate(segments):
        message = []
        if index == 0 and observation.metadata.get("message_id"):
            message.append({"type": "reply", "data": {"id": observation.metadata["message_id"]}})
        message.append(segment)
        response = await transport.action(action, {**params, "message": message})
        if response.get("status") != "ok" and index == 0 and len(message) > 1:
            response = await transport.action(action, {**params, "message": [segment]})
        if response.get("status") != "ok":
            raise RuntimeError("QQ send failed")
        if index + 1 < len(segments) and upper:
            await asyncio.sleep(random.uniform(lower, upper) / 1000)
    return len(segments)
