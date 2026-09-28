"""Send planned QQ text and emoji segments in order."""
import asyncio
import random

from zhaoxi.config.external_timing import load_external_timing


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


async def send_reply(transport, observation, content, *, settings=None) -> int:
    kind = observation.conversation_kind
    if kind == "group":
        params = {"group_id": int(observation.conversation_id)}
        action = "send_group_msg"
        maximum = getattr(settings, "group_reply_max_segments", 3)
    elif kind == "private":
        params = {"user_id": int(getattr(observation, "actor_ref", None) or observation.conversation_id)}
        action = "send_private_msg"
        maximum = getattr(settings, "private_reply_max_segments", 4)
    else:
        raise ValueError("unsupported conversation")
    segments = _bounded([{"type": part.type, "data": {"text": part.text} if part.type == "text" else {"file": part.data}} for part in content.parts], maximum)
    if not segments:
        raise ValueError("empty QQ reply")
    lower = getattr(settings, "reply_segment_delay_min_ms", 300)
    upper = max(lower, getattr(settings, "reply_segment_delay_max_ms", 800))
    if settings is not None:
        interval = load_external_timing(settings.interface_settings_path).reply_interval_seconds
        if interval is not None:
            lower = upper = round(interval * 1000)
    for index, segment in enumerate(segments):
        message = []
        if index == 0 and (getattr(observation, "message_ref", None) or getattr(observation, "metadata", {}).get("message_id")):
            message.append({"type": "reply", "data": {"id": (getattr(observation, "message_ref", None) or observation.metadata["message_id"])}})
        message.append(segment)
        response = await transport.action(action, {**params, "message": message})
        if response.get("status") != "ok" and index == 0 and len(message) > 1:
            response = await transport.action(action, {**params, "message": [segment]})
        if response.get("status") != "ok":
            raise RuntimeError("QQ send failed")
        if index + 1 < len(segments) and upper:
            await asyncio.sleep(random.uniform(lower, upper) / 1000)
    return len(segments)
