import hashlib
import sys
import wave
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from zhaoxi.voice.models import AudioCapture, AudioSpec
from zhaoxi.voice.recorder_sounddevice import SoundDeviceRecorder
from zhaoxi.voice.stt_openai import OpenAICompatibleSTT
from zhaoxi.voice.temp_store import VoiceTempStore
from zhaoxi.voice.tts_windows import WindowsSpeechHandle, WindowsTextToSpeech


def make_capture(tmp_path):
    path = tmp_path / "capture.wav"
    path.write_bytes(b"fake-wav")
    now = datetime.now(UTC)
    return AudioCapture(
        path=path,
        started_at=now,
        stopped_at=now + timedelta(seconds=1),
        duration_seconds=1,
        byte_size=path.stat().st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


async def test_openai_stt_uses_audio_endpoint_and_maps_text(tmp_path):
    capture = make_capture(tmp_path)
    seen = {}

    async def handler(request):
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["content_type"] = request.headers.get("content-type")
        return httpx.Response(200, json={"text": "  你好，朝汐  "})

    provider = OpenAICompatibleSTT(
        base_url="https://example.test/v1",
        api_key="secret-key",
        model="whisper-test",
        transport=httpx.MockTransport(handler),
    )
    transcript = await provider.transcribe(capture, language_hint="zh-CN")

    assert transcript.text == "你好，朝汐"
    assert seen["url"].endswith("/v1/audio/transcriptions")
    assert seen["authorization"] == "Bearer secret-key"
    assert "multipart/form-data" in seen["content_type"]


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "认证失败"), (429, "过于频繁"), (500, "HTTP 500")],
)
async def test_openai_stt_sanitizes_http_errors(tmp_path, status, message):
    capture = make_capture(tmp_path)
    provider = OpenAICompatibleSTT(
        base_url="https://example.test/v1",
        api_key="secret-key",
        model="whisper-test",
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json={"secret": "raw"})),
    )
    with pytest.raises(RuntimeError, match=message) as error:
        await provider.transcribe(capture)
    assert "raw" not in str(error.value)
    assert "secret-key" not in str(error.value)


async def test_sounddevice_recorder_writes_bounded_pcm_wav(tmp_path, monkeypatch):
    streams = []

    class FakeRawInputStream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
            self.stopped = False
            self.closed = False
            streams.append(self)

        def start(self):
            self.callback(b"\x01\x00" * 100, 100, None, None)

        def stop(self):
            self.stopped = True

        def abort(self):
            self.stopped = True

        def close(self):
            self.closed = True

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(RawInputStream=FakeRawInputStream))
    store = VoiceTempStore(tmp_path / "voice")
    recorder = SoundDeviceRecorder(store)
    handle = await recorder.start(AudioSpec(max_bytes=1024))
    capture = await handle.stop()

    assert streams[0].stopped and streams[0].closed
    assert capture.path.is_file()
    with wave.open(str(capture.path), "rb") as audio:
        assert audio.getframerate() == 16_000
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getnframes() == 100


async def test_sounddevice_cancel_closes_stream_and_removes_file(tmp_path, monkeypatch):
    class FakeRawInputStream:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

        def abort(self):
            pass

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(RawInputStream=FakeRawInputStream))
    recorder = SoundDeviceRecorder(VoiceTempStore(tmp_path / "voice"))
    handle = await recorder.start(AudioSpec())
    path = handle.path
    await handle.cancel()
    assert not path.exists()


async def test_windows_sapi_speaks_async_and_can_be_stopped(monkeypatch):
    calls = []

    class FakeVoice:
        Rate = 0
        Volume = 100

        def Speak(self, text, flags):
            calls.append((text, flags))

    voice = FakeVoice()
    provider = WindowsTextToSpeech(rate=2, volume=80)
    monkeypatch.setattr(provider, "_create_voice", lambda: voice)

    handle = await provider.speak("你好")
    await handle.stop()
    await handle.stop()

    assert calls == [("你好", 3), ("", 3)]


async def test_windows_sapi_wait_completes_without_playing_audio():
    class FakeVoice:
        def __init__(self):
            self.polls = 0

        def WaitUntilDone(self, timeout):
            self.polls += 1
            return self.polls == 2

    handle = WindowsSpeechHandle(FakeVoice())
    await handle.wait()
    assert handle._closed
