from zhaoxi.perception.models import Observation, AttentionHint


def route(item: Observation) -> AttentionHint:
    if item.metadata.get("self_message") or item.attention_hint == AttentionHint.IGNORE:
        return AttentionHint.IGNORE
    if item.directed_to_zhaoxi or item.attention_hint in (AttentionHint.DIRECT, AttentionHint.URGENT):
        return AttentionHint.DIRECT
    if item.conversation_kind == "private":
        return AttentionHint.DIRECT
    return AttentionHint.AMBIENT
