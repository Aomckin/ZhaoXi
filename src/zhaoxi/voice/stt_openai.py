"""OpenAI-compatible audio transcription provider."""

from __future__ import annotations

import httpx

from zhaoxi.voice.models import AudioCapture, Transcript


class OpenAICompatibleSTT:
    name = "openai-compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 45,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def transcribe(
        self,
        capture: AudioCapture,
        *,
        language_hint: str | None = None,
    ) -> Transcript:
        if not self.api_key or not self.model:
            raise RuntimeError("STT 缺少 API Key 或模型配置。")
        if not capture.path.is_file():
            raise RuntimeError("待识别音频不存在。")
        data = {"model": self.model}
        if language_hint:
            data["language"] = language_hint.split("-", 1)[0]
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                with capture.path.open("rb") as audio:
                    response = await client.post(
                        f"{self.base_url}/audio/transcriptions",
                        headers=headers,
                        data=data,
                        files={"file": ("capture.wav", audio, "audio/wav")},
                    )
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise RuntimeError("STT 请求超时，请重试或改用文字输入。") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                message = "STT 认证失败，请检查配置。"
            elif status == 429:
                message = "STT 请求过于频繁，请稍后重试。"
            else:
                message = f"STT 服务返回错误（HTTP {status}）。"
            raise RuntimeError(message) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError("STT 服务暂时不可用或返回了无效结果。") from exc
        text = str(payload.get("text", "")).strip()
        return Transcript(
            capture_id=capture.capture_id,
            text=text,
            language=language_hint,
            provider=self.name,
            duration_seconds=capture.duration_seconds,
        )

