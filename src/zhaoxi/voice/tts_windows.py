"""Local Windows 10 TTS using the built-in SAPI5 COM voice."""

from __future__ import annotations

import asyncio


_SVS_FLAGS_ASYNC = 1
_SVS_PURGE_BEFORE_SPEAK = 2


class WindowsSpeechHandle:
    def __init__(self, voice) -> None:
        self.voice = voice
        self._closed = False

    async def stop(self) -> None:
        if self._closed:
            return
        self.voice.Speak("", _SVS_FLAGS_ASYNC | _SVS_PURGE_BEFORE_SPEAK)
        self._closed = True

    async def wait(self) -> None:
        while not self._closed:
            if self.voice.WaitUntilDone(1):
                self._closed = True
                return
            await asyncio.sleep(0.05)


class WindowsTextToSpeech:
    name = "windows-sapi5"

    def __init__(self, *, voice: str = "", rate: int = 0, volume: int = 100) -> None:
        self.voice_name = voice
        self.rate = rate
        self.volume = volume

    def _create_voice(self):
        try:
            from comtypes.client import CreateObject
        except ImportError as exc:
            raise RuntimeError("Windows SAPI5 TTS 依赖未安装。") from exc
        voice = CreateObject("SAPI.SpVoice")
        voice.Rate = self.rate
        voice.Volume = self.volume
        if self.voice_name:
            for token in voice.GetVoices():
                if token.GetDescription() == self.voice_name:
                    voice.Voice = token
                    break
            else:
                raise RuntimeError(f"没有找到 Windows TTS 声音：{self.voice_name}")
        return voice

    async def speak(self, text: str) -> WindowsSpeechHandle:
        voice = self._create_voice()
        handle = WindowsSpeechHandle(voice)
        try:
            voice.Speak(text, _SVS_FLAGS_ASYNC | _SVS_PURGE_BEFORE_SPEAK)
        except Exception:
            await handle.stop()
            raise
        return handle

    def list_voices(self) -> list[str]:
        voice = self._create_voice()
        return [str(token.GetDescription()) for token in voice.GetVoices()]
