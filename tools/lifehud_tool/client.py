"""Unified HTTP boundary for Life HUD public business APIs."""

from pathlib import Path
from typing import Any, Callable, TypeVar

import httpx
from pydantic import ValidationError

from tools.lifehud_tool.errors import LifeHudError, UnsupportedSchemaVersion
from tools.lifehud_tool.autostart import LifeHudAutoStarter, connection_unavailable, local_lifehud_url
from tools.lifehud_tool.models import (
    AgentEnvelope,
    DreamsContext,
    FocusContext,
    FocusSession,
    GrowthContext,
    JournalContext,
    LifeContext,
    MediaContext,
    RecentContext,
    StatusContext,
    TasksContext,
    TodayContext,
)
from tools.lifehud_tool.time_display import LifeHudTimeDisplay
from zhaoxi.sdk import RetryPolicy, retry_async

ContextModel = TypeVar("ContextModel", bound=AgentEnvelope)


class LifeHudClient:
    def __init__(
        self,
        base_url: str,
        *,
        context_path: str = "/api/agent/context",
        schema_version: str = "1",
        timeout: float = 10,
        max_retries: int = 2,
        display_timezone: str = "Asia/Shanghai",
        retry_backoff_seconds: float = 0.1,
        transport: httpx.AsyncBaseTransport | None = None,
        autostart: bool = False,
        project_dir: str | Path | None = None,
        startup_timeout_seconds: float = 8,
        startup_poll_seconds: float = 0.4,
        autostart_launcher: Callable[[], object] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.context_path = "/" + context_path.strip("/")
        self.schema_version = schema_version
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0, retry_backoff_seconds)
        self.transport = transport
        self.time_display = LifeHudTimeDisplay(display_timezone)
        self.autostarter = (
            LifeHudAutoStarter(
                base_url=self.base_url, context_path=self.context_path,
                schema_version=self.schema_version,
                project_dir=project_dir or Path(__file__).resolve().parents[3] / "Life HUD",
                timeout_seconds=startup_timeout_seconds,
                poll_interval_seconds=startup_poll_seconds,
                transport=transport, launcher=autostart_launcher,
            ) if autostart and local_lifehud_url(self.base_url) else None
        )

    @property
    def display_timezone(self) -> str:
        return self.time_display.timezone_name

    def dump_for_display(self, value: AgentEnvelope | FocusSession | Any) -> Any:
        """Convert instants only in the outbound tool payload; source models stay UTC."""
        if isinstance(value, (AgentEnvelope, FocusSession)):
            return self.time_display.dump(value)
        return self.time_display._convert(value)

    async def today(self) -> TodayContext:
        return await self._context("/today", TodayContext)

    async def recent(self, days: int = 7) -> RecentContext:
        return await self._context("/recent", RecentContext, params={"days": days})

    async def status(self) -> StatusContext:
        return await self._context("/status", StatusContext)

    async def focus(self) -> FocusContext:
        return await self._context("/focus", FocusContext)

    async def tasks(self) -> TasksContext:
        return await self._context("/tasks", TasksContext)

    async def dreams(self) -> DreamsContext:
        return await self._context("/dreams", DreamsContext)

    async def life(self) -> LifeContext:
        return await self._context("/life", LifeContext)

    async def journal(self, limit: int = 20) -> JournalContext:
        return await self._context("/journal", JournalContext, params={"limit": limit})

    async def media(self) -> MediaContext:
        return await self._context("/media", MediaContext)

    async def growth(self) -> GrowthContext:
        return await self._context("/growth", GrowthContext)

    async def current(self) -> FocusSession | None:
        """Compatibility helper backed by the official Agent Context API."""
        return (await self.focus()).focus.active

    async def start_iron_curtain(
        self, title: str, related_task_ids: list[str]
    ) -> FocusSession:
        response = await self._request(
            "POST",
            "/api/focus/start",
            retry_read=False,
            json={
                "mode": "IRON_CURTAIN",
                "title": title,
                "taskId": None,
                "plannedMinutes": None,
                "breakMinutes": None,
                "relatedTaskIds": related_task_ids,
            },
        )
        return self._session(response)

    async def complete(self, session_id: str, note: str | None) -> FocusSession:
        response = await self._request(
            "POST",
            f"/api/focus/{session_id}/complete",
            retry_read=False,
            json={"note": note},
        )
        return self._session(response)

    async def request_json(self, method: str, path: str, *, body: dict[str, Any] | None = None,
                           params: dict[str, Any] | None = None) -> Any:
        """Business writes are sent once; only GET uses the existing retry policy."""
        response = await self._request(method, path, retry_read=method == "GET",
                                       **({"json": body} if body is not None else {}),
                                       **({"params": params} if params else {}))
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise LifeHudError("Life HUD 返回了无效 JSON。", code="invalid_lifehud_response") from exc

    async def upload_image(self, content: bytes, filename: str, mime: str) -> str:
        response = await self._request("POST", "/api/images", retry_read=False,
                                       files={"file": (filename, content, mime)})
        try:
            path = response.json()["path"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LifeHudError("Life HUD 图片上传响应无效。", code="invalid_lifehud_response") from exc
        if not isinstance(path, str) or not path.startswith("/uploads/"):
            raise LifeHudError("Life HUD 图片路径无效。", code="invalid_lifehud_response")
        return path

    async def _context(
        self,
        path: str,
        model: type[ContextModel],
        **kwargs: Any,
    ) -> ContextModel:
        response = await self._request(
            "GET", f"{self.context_path}{path}", retry_read=True, **kwargs
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise LifeHudError(
                "Life HUD 返回了无效 JSON。", code="invalid_lifehud_response"
            ) from exc
        actual = payload.get("schemaVersion") if isinstance(payload, dict) else None
        if actual != self.schema_version:
            raise UnsupportedSchemaVersion(actual, self.schema_version)
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise LifeHudError(
                "Life HUD Agent Context 数据不符合 schema 1 契约。",
                code="invalid_lifehud_response",
            ) from exc

    async def _request(
        self, method: str, path: str, *, retry_read: bool, **kwargs: Any
    ) -> httpx.Response:
        if self.autostarter is not None:
            await self.autostarter.ensure_ready()
        retries = self.max_retries if retry_read and method == "GET" else 0
        async def send() -> httpx.Response:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
                trust_env=not local_lifehud_url(self.base_url),
            ) as client:
                return await client.request(method, path, **kwargs)

        async def operation() -> httpx.Response:
            try:
                response = await send()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if self.autostarter is not None and connection_unavailable(exc):
                    self.autostarter.mark_unready()
                    await self.autostarter.ensure_ready()
                    try:
                        response = await send()  # Refused TCP connect could not have committed a write.
                    except (httpx.TimeoutException, httpx.NetworkError) as retry_exc:
                        raise LifeHudError("Life HUD 启动后原请求仍无法连接。",
                                           code="lifehud_unavailable", retryable=retry_read) from retry_exc
                else:
                    raise LifeHudError(
                        "Life HUD 当前不可访问。",
                        code="lifehud_unavailable",
                        retryable=retry_read,
                    ) from exc
            return self._validate_status(response, retry_read=retry_read)

        return await retry_async(
            operation,
            policy=RetryPolicy(
                max_attempts=retries + 1,
                base_delay_seconds=self.retry_backoff_seconds,
                max_delay_seconds=self.retry_backoff_seconds * (2 ** max(0, retries - 1)),
                jitter_ratio=0,
            ),
            should_retry=lambda exc: isinstance(exc, LifeHudError) and exc.retryable,
        )

    @staticmethod
    def _validate_status(response: httpx.Response, *, retry_read: bool) -> httpx.Response:
        if response.status_code == 400:
            try:
                detail = response.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            message = str(detail) if detail else "Life HUD 请求参数无效。"
            raise LifeHudError(message, code="lifehud_invalid_argument")
        if response.status_code == 409:
            raise LifeHudError("Life HUD 当前状态与该操作冲突。", code="lifehud_conflict")
        if response.status_code == 404:
            raise LifeHudError("Life HUD 中没有找到目标资源。", code="lifehud_not_found")
        if response.status_code == 413:
            raise LifeHudError("图片超过 Life HUD 的 64 MB 上限。", code="image_too_large")
        if response.status_code >= 500:
            raise LifeHudError(
                "Life HUD 暂时不可用。",
                code="lifehud_server_error",
                retryable=retry_read,
            )
        if response.status_code >= 400:
            raise LifeHudError(
                f"Life HUD 拒绝了请求（HTTP {response.status_code}）。",
                code="lifehud_request_rejected",
            )
        return response

    @staticmethod
    def _session(response: httpx.Response) -> FocusSession:
        try:
            return FocusSession.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise LifeHudError(
                "Life HUD 返回了无法识别的 Focus 数据。",
                code="invalid_lifehud_response",
            ) from exc
