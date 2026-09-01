"""Bounded domain models for voice capture, transcription, and playback."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class VoiceStatus(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    REVIEWING = "reviewing"
    SENDING = "sending"
    SPEAKING = "speaking"
    CANCELLING = "cancelling"
    FAILED = "failed"


class AudioSpec(BaseModel):
    sample_rate_hz: int = Field(default=16_000, ge=8_000, le=48_000)
    channels: int = Field(default=1, ge=1, le=2)
    sample_width_bytes: int = Field(default=2, ge=1, le=4)
    encoding: str = Field(default="wav", pattern=r"^(wav|pcm_s16le)$")
    max_seconds: float = Field(default=60, gt=0, le=300)
    max_bytes: int = Field(default=4_194_304, ge=1024, le=100_000_000)


class AudioCapture(BaseModel):
    capture_id: str = Field(default_factory=lambda: uuid4().hex)
    path: Path
    spec: AudioSpec = Field(default_factory=AudioSpec)
    started_at: datetime
    stopped_at: datetime
    duration_seconds: float = Field(ge=0)
    byte_size: int = Field(ge=0)
    device_name: str | None = Field(default=None, max_length=160)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_capture(self) -> "AudioCapture":
        if self.started_at.tzinfo is None or self.stopped_at.tzinfo is None:
            raise ValueError("音频时间必须包含时区")
        self.started_at = self.started_at.astimezone(UTC)
        self.stopped_at = self.stopped_at.astimezone(UTC)
        if self.stopped_at < self.started_at:
            raise ValueError("录音停止时间不能早于开始时间")
        if self.duration_seconds > self.spec.max_seconds + 0.5:
            raise ValueError("录音超过最大时长")
        if self.byte_size > self.spec.max_bytes:
            raise ValueError("录音超过最大大小")
        return self


class Transcript(BaseModel):
    transcript_id: str = Field(default_factory=lambda: uuid4().hex)
    capture_id: str
    text: str = Field(max_length=20_000)
    language: str | None = Field(default=None, max_length=32)
    provider: str = Field(min_length=1, max_length=80)
    duration_seconds: float = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()


class VoiceStateEvent(BaseModel):
    operation_id: str
    previous_status: VoiceStatus
    status: VoiceStatus
    reason: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

