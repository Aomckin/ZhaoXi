"""Bounded PCM WAV recorder backed by sounddevice/PortAudio."""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
import wave
from datetime import UTC, datetime

from zhaoxi.voice.models import AudioCapture, AudioSpec
from zhaoxi.voice.temp_store import VoiceTempStore


class SoundDeviceRecording:
    def __init__(self, stream, spec: AudioSpec, store: VoiceTempStore, device_name: str | None) -> None:
        self.stream = stream
        self.spec = spec
        self.store = store
        self.device_name = device_name
        self.started_at = datetime.now(UTC)
        self.started_monotonic = time.monotonic()
        self.path = store.create_wav_path()
        self.frames = bytearray()
        self._lock = threading.Lock()
        self._closed = False

    def callback(self, data, frames, time_info, status) -> None:
        del frames, time_info, status
        with self._lock:
            remaining = max(0, self.spec.max_bytes - 44 - len(self.frames))
            if remaining > 0:
                self.frames.extend(bytes(data)[:remaining])

    async def stop(self) -> AudioCapture:
        if self._closed:
            raise RuntimeError("录音已经结束")
        self._closed = True
        await asyncio.to_thread(self.stream.stop)
        await asyncio.to_thread(self.stream.close)
        duration = min(time.monotonic() - self.started_monotonic, self.spec.max_seconds)
        with self._lock:
            payload = bytes(self.frames)
        await asyncio.to_thread(self._write_wav, payload)
        return AudioCapture(
            path=self.path,
            spec=self.spec,
            started_at=self.started_at,
            stopped_at=datetime.now(UTC),
            duration_seconds=duration,
            byte_size=self.path.stat().st_size,
            device_name=self.device_name,
            sha256=hashlib.sha256(self.path.read_bytes()).hexdigest(),
        )

    async def cancel(self) -> None:
        if not self._closed:
            self._closed = True
            await asyncio.to_thread(self.stream.abort)
            await asyncio.to_thread(self.stream.close)
        self.store.remove(self.path)

    def _write_wav(self, payload: bytes) -> None:
        with wave.open(str(self.path), "wb") as output:
            output.setnchannels(self.spec.channels)
            output.setsampwidth(self.spec.sample_width_bytes)
            output.setframerate(self.spec.sample_rate_hz)
            output.writeframes(payload)


class SoundDeviceRecorder:
    def __init__(self, store: VoiceTempStore) -> None:
        self.store = store

    async def start(self, spec: AudioSpec, device_name: str | None = None) -> SoundDeviceRecording:
        try:
            import sounddevice as sound
        except ImportError as exc:
            raise RuntimeError("录音依赖未安装，请安装项目的 voice 可选依赖。") from exc
        holder = {}

        def callback(data, frames, time_info, status):
            recording = holder.get("recording")
            if recording is not None:
                recording.callback(data, frames, time_info, status)

        stream = sound.RawInputStream(
            samplerate=spec.sample_rate_hz,
            channels=spec.channels,
            dtype="int16",
            device=device_name or None,
            callback=callback,
        )
        recording = SoundDeviceRecording(stream, spec, self.store, device_name)
        holder["recording"] = recording
        try:
            await asyncio.to_thread(stream.start)
        except Exception:
            self.store.remove(recording.path)
            raise
        return recording

    @staticmethod
    def list_devices() -> list[dict[str, str | int]]:
        try:
            import sounddevice as sound
        except ImportError as exc:
            raise RuntimeError("录音依赖未安装，请安装项目的 voice 可选依赖。") from exc
        devices = []
        for index, device in enumerate(sound.query_devices()):
            if int(device["max_input_channels"]) > 0:
                devices.append({"id": index, "name": str(device["name"])[:160]})
        return devices
