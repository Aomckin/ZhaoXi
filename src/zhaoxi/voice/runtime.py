"""Cancellable Voice state machine independent from concrete audio providers."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from zhaoxi.interfaces import InterfaceChannel, InterfaceGateway, UnifiedMessage, UnifiedResponse
from zhaoxi.voice.models import AudioCapture, AudioSpec, Transcript, VoiceStateEvent, VoiceStatus
from zhaoxi.voice.protocols import (
    AudioRecorder,
    RecordingHandle,
    SpeechHandle,
    SpeechToTextProvider,
    TextToSpeechProvider,
)
from zhaoxi.voice.sanitizer import sanitize_for_speech
from zhaoxi.voice.temp_store import VoiceTempStore


class VoiceRuntime:
    def __init__(
        self,
        *,
        recorder: AudioRecorder,
        stt: SpeechToTextProvider,
        tts: TextToSpeechProvider,
        temp_store: VoiceTempStore,
        spec: AudioSpec | None = None,
        language: str = "zh-CN",
    ) -> None:
        self.recorder = recorder
        self.stt = stt
        self.tts = tts
        self.temp_store = temp_store
        self.spec = spec or AudioSpec()
        self.language = language
        self.status = VoiceStatus.IDLE
        self.events: list[VoiceStateEvent] = []
        self.transcript: Transcript | None = None
        self.capture: AudioCapture | None = None
        self._recording: RecordingHandle | None = None
        self._speech: SpeechHandle | None = None
        self._speech_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._operation_id = uuid4().hex

    async def start_recording(self, *, device_name: str | None = None) -> None:
        async with self._lock:
            self._require(VoiceStatus.IDLE)
            self._operation_id = uuid4().hex
            self._recording = await self.recorder.start(self.spec, device_name)
            self._transition(VoiceStatus.RECORDING, "user_started")

    async def stop_recording(self) -> Transcript:
        async with self._lock:
            self._require(VoiceStatus.RECORDING)
            recording = self._recording
            self._recording = None
            self._transition(VoiceStatus.TRANSCRIBING, "user_stopped")
        assert recording is not None
        capture: AudioCapture | None = None
        try:
            capture = await recording.stop()
            transcript = await self.stt.transcribe(capture, language_hint=self.language)
        except asyncio.CancelledError:
            await self.cancel("transcription_cancelled")
            raise
        except Exception:
            if capture is not None:
                self.temp_store.remove(capture.path)
            async with self._lock:
                self._transition(VoiceStatus.FAILED, "transcription_failed")
                self._transition(VoiceStatus.IDLE, "recoverable_failure")
            raise
        async with self._lock:
            self.capture = capture
            self.transcript = transcript
            self._transition(VoiceStatus.REVIEWING, "transcript_ready")
            return transcript

    async def confirm_transcript(
        self,
        text: str,
        *,
        gateway: InterfaceGateway,
        session_id: str = "local",
        request_id: str | None = None,
    ) -> UnifiedResponse:
        normalized = text.strip()
        if not normalized:
            raise ValueError("确认后的 transcript 不能为空")
        async with self._lock:
            self._require(VoiceStatus.REVIEWING)
            provider_name = self.transcript.provider if self.transcript else self.stt.name
            self._transition(VoiceStatus.SENDING, "user_confirmed")
        try:
            response = await gateway.chat(UnifiedMessage(
                request_id=request_id or uuid4().hex,
                session_id=session_id,
                channel=InterfaceChannel.VOICE,
                content=normalized,
                metadata={"input_mode": "push_to_talk", "stt_provider": provider_name},
            ))
        finally:
            async with self._lock:
                self._cleanup_capture()
                self.transcript = None
                self._transition(VoiceStatus.IDLE, "send_finished")
        return response

    async def speak(self, text: str, *, max_chars: int = 1200) -> bool:
        spoken = sanitize_for_speech(text, max_chars=max_chars)
        if not spoken:
            return False
        async with self._lock:
            self._require(VoiceStatus.IDLE)
            speech = await self.tts.speak(spoken)
            self._speech = speech
            self._transition(VoiceStatus.SPEAKING, "speech_started")
            self._speech_task = asyncio.create_task(
                self._watch_speech(speech), name="zhaoxi-voice-speech"
            )
        return True

    async def stop_speaking(self) -> None:
        async with self._lock:
            if self.status is not VoiceStatus.SPEAKING:
                return
            speech = self._speech
            speech_task = self._speech_task
            self._speech = None
            self._speech_task = None
            self._transition(VoiceStatus.CANCELLING, "speech_stop")
        if speech_task is not None:
            speech_task.cancel()
        if speech is not None:
            await speech.stop()
        async with self._lock:
            self._transition(VoiceStatus.IDLE, "speech_stopped")

    async def cancel(self, reason: str = "user_cancelled") -> None:
        async with self._lock:
            if self.status is VoiceStatus.IDLE:
                return
            recording, speech, speech_task = self._recording, self._speech, self._speech_task
            self._recording = None
            self._speech = None
            self._speech_task = None
            self._transition(VoiceStatus.CANCELLING, reason)
        if speech_task is not None:
            speech_task.cancel()
        if recording is not None:
            await recording.cancel()
        if speech is not None:
            await speech.stop()
        async with self._lock:
            self._cleanup_capture()
            self.transcript = None
            self._transition(VoiceStatus.IDLE, "cancelled")

    async def _watch_speech(self, speech: SpeechHandle) -> None:
        try:
            await speech.wait()
        except asyncio.CancelledError:
            return
        except Exception:
            reason = "speech_failed"
        else:
            reason = "speech_finished"
        async with self._lock:
            if self._speech is not speech or self.status is not VoiceStatus.SPEAKING:
                return
            self._speech = None
            self._speech_task = None
            self._transition(VoiceStatus.IDLE, reason)

    def _cleanup_capture(self) -> None:
        if self.capture is not None:
            self.temp_store.remove(self.capture.path)
            self.capture = None

    def _require(self, expected: VoiceStatus) -> None:
        if self.status is not expected:
            raise RuntimeError(f"Voice 状态必须是 {expected.value}，当前为 {self.status.value}")

    def _transition(self, status: VoiceStatus, reason: str) -> None:
        previous = self.status
        self.status = status
        self.events.append(VoiceStateEvent(
            operation_id=self._operation_id,
            previous_status=previous,
            status=status,
            reason=reason,
        ))
