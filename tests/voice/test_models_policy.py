from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from zhaoxi.voice.models import AudioCapture, AudioSpec
from zhaoxi.voice.policy import SpeechAction, SpeechContext, SpeechPolicy
from zhaoxi.voice.sanitizer import sanitize_for_speech


def test_audio_spec_and_capture_are_bounded():
    spec = AudioSpec(max_seconds=10, max_bytes=2048)
    capture = AudioCapture(
        path=Path("capture.wav"),
        spec=spec,
        started_at=datetime.now(UTC),
        stopped_at=datetime.now(UTC) + timedelta(seconds=1),
        duration_seconds=1,
        byte_size=1024,
        sha256="a" * 64,
    )
    assert capture.spec.sample_rate_hz == 16_000
    with pytest.raises(ValidationError, match="最大大小"):
        AudioCapture(
            path=Path("too-big.wav"),
            spec=spec,
            started_at=datetime.now(UTC),
            stopped_at=datetime.now(UTC),
            duration_seconds=1,
            byte_size=4096,
            sha256="b" * 64,
        )


@pytest.mark.parametrize(
    ("context", "action"),
    [
        (SpeechContext(recording=True), SpeechAction.STOP_CURRENT),
        (SpeechContext(voice_enabled=False), SpeechAction.TEXT_ONLY),
        (SpeechContext(voice_enabled=True, quiet=True, explicit_user_action=True), SpeechAction.TEXT_ONLY),
        (SpeechContext(voice_enabled=True, night=True), SpeechAction.TEXT_ONLY),
        (SpeechContext(voice_enabled=True, permission_pending=True), SpeechAction.TEXT_ONLY),
        (SpeechContext(voice_enabled=True, explicit_user_action=True), SpeechAction.SPEAK_NOW),
        (
            SpeechContext(
                voice_enabled=True,
                auto_speak=True,
                response_from_voice=True,
                text_length=500,
                max_auto_chars=400,
            ),
            SpeechAction.REQUIRE_CLICK,
        ),
        (
            SpeechContext(
                voice_enabled=True,
                auto_speak=True,
                response_from_voice=True,
                text_length=20,
            ),
            SpeechAction.SPEAK_NOW,
        ),
    ],
)
def test_speech_policy_is_deterministic(context, action):
    assert SpeechPolicy().decide(context)[0] is action


def test_sanitizer_removes_non_spoken_internal_shapes():
    assert sanitize_for_speech('{"tool": "secret"}') == ""
    spoken = sanitize_for_speech("## 标题\n看[文档](https://example.com)\n```python\nprint(1)\n```")
    assert "https" not in spoken
    assert "```" not in spoken
    assert "文档（链接）" in spoken
    assert "包含代码" in spoken

