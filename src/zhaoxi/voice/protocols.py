"""Injectable contracts for recorder, STT, TTS, and speech handles."""

from __future__ import annotations

from typing import Protocol

from zhaoxi.voice.models import AudioCapture, AudioSpec, Transcript


class RecordingHandle(Protocol):
    async def stop(self) -> AudioCapture: ...

    async def cancel(self) -> None: ...


class AudioRecorder(Protocol):
    async def start(self, spec: AudioSpec, device_name: str | None = None) -> RecordingHandle: ...


class SpeechToTextProvider(Protocol):
    name: str

    async def transcribe(
        self,
        capture: AudioCapture,
        *,
        language_hint: str | None = None,
    ) -> Transcript: ...


class SpeechHandle(Protocol):
    async def stop(self) -> None: ...

    async def wait(self) -> None: ...


class TextToSpeechProvider(Protocol):
    name: str

    async def speak(self, text: str) -> SpeechHandle: ...

