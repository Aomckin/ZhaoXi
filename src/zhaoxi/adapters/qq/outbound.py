"""Reply to the original OneBot conversation, with an optional reply segment."""


async def send_reply(transport, observation, content: str):
    kind = observation.conversation_kind
    params = {}
    message = []
    if observation.metadata.get("message_id"):
        message.append({"type": "reply", "data": {"id": observation.metadata["message_id"]}})
    message.append({"type": "text", "data": {"text": content}})
    params["message"] = message
    if kind == "group":
        params["group_id"] = int(observation.conversation_id)
        action = "send_group_msg"
    elif kind == "private":
        params["user_id"] = int(observation.actor_id)
        action = "send_private_msg"
    else:
        raise ValueError("unsupported conversation")
    result = await transport.action(action, params)
    if result.get("status") != "ok":
        # Some OneBot implementations reject reply segments. Retry as plain text.
        params["message"] = content
        result = await transport.action(action, params)
    if result.get("status") != "ok":
        raise RuntimeError("QQ send failed")
    return result
