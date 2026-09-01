"""Deterministic speech output policy."""

from dataclasses import dataclass
from enum import StrEnum


class SpeechAction(StrEnum):
    SPEAK_NOW = "speak_now"
    TEXT_ONLY = "text_only"
    REQUIRE_CLICK = "require_click"
    STOP_CURRENT = "stop_current"


@dataclass(slots=True, frozen=True)
class SpeechContext:
    voice_enabled: bool = False
    auto_speak: bool = False
    explicit_user_action: bool = False
    response_from_voice: bool = False
    quiet: bool = False
    night: bool = False
    recording: bool = False
    permission_pending: bool = False
    text_length: int = 0
    max_auto_chars: int = 400


class SpeechPolicy:
    def decide(self, context: SpeechContext) -> tuple[SpeechAction, str]:
        if context.recording:
            return SpeechAction.STOP_CURRENT, "recording_active"
        if not context.voice_enabled:
            return SpeechAction.TEXT_ONLY, "voice_disabled"
        if context.quiet:
            return SpeechAction.TEXT_ONLY, "quiet_mode"
        if context.night:
            return SpeechAction.TEXT_ONLY, "night_mode"
        if context.permission_pending:
            return SpeechAction.TEXT_ONLY, "permission_pending"
        if context.explicit_user_action:
            return SpeechAction.SPEAK_NOW, "explicit_user_action"
        if not context.auto_speak or not context.response_from_voice:
            return SpeechAction.TEXT_ONLY, "auto_speak_disabled"
        if context.text_length > context.max_auto_chars:
            return SpeechAction.REQUIRE_CLICK, "response_too_long"
        return SpeechAction.SPEAK_NOW, "voice_response"

