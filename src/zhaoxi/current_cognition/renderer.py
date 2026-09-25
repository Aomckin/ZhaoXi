"""Render a compact always-on account, not a database listing."""

from .models import CurrentCognitionState


def render(state: CurrentCognitionState) -> str:
    if not state.narrative.strip():
        return "[Current Cognition]\n近期状态尚未形成。"
    lines = ["[Current Cognition]", state.narrative.strip()]
    if state.ongoing_threads:
        lines.append("仍在持续：" + "；".join(state.ongoing_threads) + "。")
    if state.attention:
        lines.append("需要留意：" + "；".join(state.attention) + "。")
    return "\n\n".join(lines)
