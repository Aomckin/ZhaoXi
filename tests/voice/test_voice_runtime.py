import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from zhaoxi.core.agent import AgentResponse
from zhaoxi.core.conversation import Conversation
from zhaoxi.interfaces import InterfaceGateway
from zhaoxi.voice.models import AudioCapture, AudioSpec, Transcript, VoiceStatus
from zhaoxi.voice.runtime import VoiceRuntime
from zhaoxi.voice.temp_store import VoiceTempStore


class FakeRecording:
    def __init__(self, capture):
        self.capture = capture
        self.cancelled = False

    async def stop(self):
        return self.capture

    async def cancel(self):
        self.cancelled = True
        self.capture.path.unlink(missing_ok=True)


class FakeRecorder:
    def __init__(self, capture):
        self.capture = capture
        self.handles = []

    async def start(self, spec, device_name=None):
        handle = FakeRecording(self.capture)
        self.handles.append(handle)
        return handle


class FakeSTT:
    name = "fake-stt"

    def __init__(self, text="原始转写", error=None):
        self.text = text
        self.error = error

    async def transcribe(self, capture, *, language_hint=None):
        if self.error:
            raise self.error
        return Transcript(
            capture_id=capture.capture_id,
            text=self.text,
            language=language_hint,
            provider=self.name,
            duration_seconds=capture.duration_seconds,
        )


class FakeSpeech:
    def __init__(self):
        self.stopped = False
        self.finished = asyncio.Event()

    async def stop(self):
        self.stopped = True

    async def wait(self):
        await self.finished.wait()


class FakeTTS:
    name = "fake-tts"

    def __init__(self):
        self.spoken = []
        self.handles = []

    async def speak(self, text):
        self.spoken.append(text)
        handle = FakeSpeech()
        self.handles.append(handle)
        return handle


class FakeAgent:
    def __init__(self):
        self.conversation = Conversation()
        self.tool_executor = SimpleNamespace(gateway=SimpleNamespace(store=SimpleNamespace(pending={})))
        self._pending_permissions = {}
        self.planner = None
        self.workflow = None

    async def run_natural(self, content):
        self.conversation.add_user(content)
        self.conversation.add_assistant("收到")
        return AgentResponse(content="收到", request_id="core-voice", steps=1)


def build_runtime(tmp_path, *, stt=None):
    store = VoiceTempStore(tmp_path / "voice")
    path = store.create_wav_path()
    payload = b"fake-wav"
    path.write_bytes(payload)
    now = datetime.now(UTC)
    spec = AudioSpec()
    capture = AudioCapture(
        path=path,
        spec=spec,
        started_at=now,
        stopped_at=now + timedelta(seconds=1),
        duration_seconds=1,
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    recorder = FakeRecorder(capture)
    tts = FakeTTS()
    runtime = VoiceRuntime(
        recorder=recorder,
        stt=stt or FakeSTT(),
        tts=tts,
        temp_store=store,
        spec=spec,
    )
    return runtime, recorder, tts, path


async def test_voice_input_requires_review_before_gateway(tmp_path):
    runtime, _, _, path = build_runtime(tmp_path)
    agent = FakeAgent()
    gateway = InterfaceGateway(agent)

    await runtime.start_recording()
    assert runtime.status is VoiceStatus.RECORDING
    transcript = await runtime.stop_recording()
    assert transcript.text == "原始转写"
    assert runtime.status is VoiceStatus.REVIEWING
    assert agent.conversation.messages == []

    response = await runtime.confirm_transcript(
        "编辑后的文本",
        gateway=gateway,
        request_id="voice-request",
    )
    assert response.content == "收到"
    assert agent.conversation.messages[0].content == "编辑后的文本"
    assert runtime.status is VoiceStatus.IDLE
    assert not path.exists()


async def test_recording_cancel_is_idempotent_and_cleans_state(tmp_path):
    runtime, recorder, _, path = build_runtime(tmp_path)
    await runtime.start_recording()
    await runtime.cancel()
    await runtime.cancel()
    assert recorder.handles[0].cancelled
    assert runtime.status is VoiceStatus.IDLE
    assert not path.exists()


async def test_transcription_failure_cleans_capture_and_recovers(tmp_path):
    runtime, _, _, path = build_runtime(tmp_path, stt=FakeSTT(error=RuntimeError("offline")))
    await runtime.start_recording()
    with pytest.raises(RuntimeError, match="offline"):
        await runtime.stop_recording()
    assert runtime.status is VoiceStatus.IDLE
    assert not path.exists()


async def test_tts_is_sanitized_and_stoppable(tmp_path):
    runtime, _, tts, _ = build_runtime(tmp_path)
    assert await runtime.speak("看[文档](https://example.com)")
    assert runtime.status is VoiceStatus.SPEAKING
    assert "https" not in tts.spoken[0]
    await runtime.stop_speaking()
    await runtime.stop_speaking()
    assert tts.handles[0].stopped
    assert runtime.status is VoiceStatus.IDLE


async def test_tts_natural_completion_returns_to_idle(tmp_path):
    runtime, _, tts, _ = build_runtime(tmp_path)
    assert await runtime.speak("测试朗读")
    tts.handles[0].finished.set()
    await asyncio.sleep(0)
    assert runtime.status is VoiceStatus.IDLE


async def test_invalid_parallel_recording_is_rejected(tmp_path):
    runtime, _, _, _ = build_runtime(tmp_path)
    await runtime.start_recording()
    with pytest.raises(RuntimeError, match="idle"):
        await runtime.start_recording()
    await runtime.cancel()
