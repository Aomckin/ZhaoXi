"""Business routing and image attachment handling for the single LifeHUD Tool."""

import base64
import binascii
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from tools.lifehud_tool.client import LifeHudClient
from tools.lifehud_tool.errors import LifeHudError
from zhaoxi.sdk import current_turn_images


RECORD_PATHS = {
    "sleep": "/api/life/sleep", "meal": "/api/life/meals",
    "exercise": "/api/life/exercises", "check_in": "/api/life/check-ins",
    "life_record": "/api/life/records",
}
RECORD_FIELDS = {
    "sleep": {"sleepTime", "wakeTime", "quality", "type", "note", "images"},
    "meal": {"mealType", "time", "description", "satisfaction", "note", "images"},
    "exercise": {"type", "startTime", "durationMinutes", "intensity", "note", "images"},
    "check_in": {"energy", "mood", "focusDesire", "fatigue", "time", "note", "images"},
    "life_record": {"type", "value", "unit", "time", "label", "note", "metadata", "images"},
}
LIFE_TYPES = {"WATER", "CAFFEINE", "ALCOHOL", "SUNLIGHT", "SOCIAL", "BODY_STATUS", "OUTDOOR", "CUSTOM"}
INSTANT_FIELDS = {"sleepTime", "wakeTime", "time", "startTime", "occurredAt", "startedAt", "endedAt", "watchedAt", "endTime"}
IMAGE_MIMES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
MAX_IMAGE_BYTES = 64 * 1024 * 1024


def _invalid(message: str, code: str = "validation_error") -> LifeHudError:
    return LifeHudError(message, code=code)


def _id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or "/" in value or "?" in value or "#" in value:
        raise _invalid("需要有效的资源 id。")
    return quote(value, safe="")


def _body(payload: dict[str, Any], allowed: set[str], *, required: set[str] = frozenset()) -> dict[str, Any]:
    body = {key: value for key, value in payload.items() if key in allowed}
    if missing := required - {key for key, value in body.items() if value is not None}:
        raise _invalid("缺少必填字段：" + ", ".join(sorted(missing)))
    for field in INSTANT_FIELDS & body.keys():
        value = body[field]
        if value is not None:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (TypeError, ValueError, AttributeError) as exc:
                raise _invalid(f"{field} 必须是带时区的 ISO-8601 时间。") from exc
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise _invalid(f"{field} 必须包含时区。")
    return body


def _image_bytes(source: str) -> tuple[bytes, str, str]:
    if source.startswith("data:"):
        header, sep, encoded = source.partition(",")
        mime = header.removeprefix("data:").removesuffix(";base64")
        if not sep or not header.endswith(";base64") or mime not in IMAGE_MIMES.values():
            raise _invalid("仅支持 PNG、JPEG、WebP 或 GIF 图片。", "unsupported_image")
        if len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
            raise _invalid("图片超过 64 MB。", "image_too_large")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise _invalid("图片 base64 无效。", "unsupported_image") from exc
        suffix = next(ext for ext, kind in IMAGE_MIMES.items() if kind == mime)
        filename = f"attachment.{suffix}"
    else:
        path = Path(source)
        if not path.is_file():
            raise _invalid("图片附件不存在。", "attachment_not_found")
        mime = IMAGE_MIMES.get(path.suffix.lower().lstrip("."))
        if mime is None:
            raise _invalid("不支持的图片类型。", "unsupported_image")
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise _invalid("图片超过 64 MB。", "image_too_large")
        raw, filename = path.read_bytes(), path.name
    valid = ((mime == "image/png" and raw.startswith(b"\x89PNG\r\n\x1a\n")) or
             (mime == "image/jpeg" and raw.startswith(b"\xff\xd8\xff")) or
             (mime == "image/webp" and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP") or
             (mime == "image/gif" and raw.startswith((b"GIF87a", b"GIF89a"))))
    if len(raw) > MAX_IMAGE_BYTES:
        raise _invalid("图片超过 64 MB。", "image_too_large")
    if not raw or not valid:
        raise _invalid("图片内容与格式不匹配。", "unsupported_image")
    return raw, filename, mime


class LivingIO:
    def __init__(self, client: LifeHudClient, enabled: dict[str, bool] | None = None):
        self.client = client
        self.enabled = enabled or {}

    def _require_enabled(self, group: str) -> None:
        if not self.enabled.get(group, True):
            raise _invalid(f"LifeHUD {group} 能力已停用。", "capability_disabled")

    async def _images(self, body: dict[str, Any]) -> bool:
        if "images" not in body or body["images"] is None:
            return False
        if not isinstance(body["images"], list):
            raise _invalid("images 必须是图片数组。")
        uploaded = False
        resolved = []
        # Validate every attachment before uploading any; never create a partial record.
        prepared = []
        for source in body["images"]:
            if not isinstance(source, str):
                raise _invalid("images 中的图片必须是路径或数据 URL。")
            if source == "<current-message-image>" or source.startswith("<current-message-image:"):
                attachments = current_turn_images()
                if source == "<current-message-image>":
                    index = 0
                else:
                    suffix = source.removeprefix("<current-message-image:").removesuffix(">")
                    if not source.endswith(">") or not suffix.isdecimal() or int(suffix) < 1:
                        raise _invalid("图片附件引用格式无效。", "attachment_not_found")
                    index = int(suffix) - 1
                if index >= len(attachments):
                    raise _invalid("当前消息图片附件不存在。", "attachment_not_found")
                source = attachments[index]
            if source.startswith("/uploads/"):
                prepared.append(source)
            else:
                self._require_enabled("image")
                prepared.append(_image_bytes(source))
        for item in prepared:
            if isinstance(item, str):
                resolved.append(item)
            else:
                try:
                    resolved.append(await self.client.upload_image(*item))
                except LifeHudError as exc:
                    if uploaded:
                        exc.image_uploaded_but_record_failed = True
                    raise
                uploaded = True
        body["images"] = resolved
        return uploaded

    async def _write(self, method: str, path: str, body: dict[str, Any] | None,
                     *, confirm_path: str | None = None, confirm_collection: str | None = None,
                     resource: str, action: str) -> dict[str, Any]:
        uploaded = False
        if body is not None:
            uploaded = await self._images(body)
        try:
            response = await self.client.request_json(method, path, body=body)
        except LifeHudError as exc:
            if uploaded:
                exc.image_uploaded_but_record_failed = True
            raise
        if confirm_path is None and isinstance(response, dict) and response.get("id"):
            confirm_path = (confirm_collection or path.rstrip("/")) + "/" + _id(response["id"])
        try:
            confirmed = await self.client.request_json("GET", confirm_path) if confirm_path else response
        except LifeHudError as exc:
            raise LifeHudError("写入已返回成功，但回读确认失败；请查询后再操作。", code="confirmation_failed") from exc
        if isinstance(confirmed, list) and isinstance(response, dict) and response.get("id"):
            matches = [item for item in confirmed if isinstance(item, dict) and item.get("id") == response["id"]]
            if not matches:
                raise LifeHudError("写入已返回成功，但回读未找到对应记录。", code="confirmation_failed")
            confirmed = matches[0]
        if (isinstance(confirmed, dict) and isinstance(response, dict) and response.get("id")
                and confirmed.get("id") is not None and confirmed["id"] != response["id"]):
            raise LifeHudError("写入已返回成功，但回读记录 id 不一致。", code="confirmation_failed")
        return {"ok": True, "action": action, "resource": resource,
                "id": confirmed.get("id") if isinstance(confirmed, dict) else None,
                "record": confirmed, "warnings": []}

    async def context(self, payload: dict[str, Any]) -> Any:
        self._require_enabled("context")
        view = payload.get("view", "today")
        readers = {"today": self.client.today, "recent": self.client.recent,
                   "status": self.client.status, "focus": self.client.focus,
                   "tasks": self.client.tasks, "dreams": self.client.dreams,
                   "life": self.client.life, "journal": self.client.journal,
                   "media": self.client.media, "growth": self.client.growth}
        if view not in readers:
            raise _invalid("不支持的 Context view。")
        if view == "recent":
            days = payload.get("days", 7)
            if not isinstance(days, int) or not 1 <= days <= 30:
                raise _invalid("days 必须在 1–30 之间。")
            return await self.client.recent(days)
        if view == "journal":
            limit = payload.get("limit", 20)
            if not isinstance(limit, int) or not 1 <= limit <= 100:
                raise _invalid("limit 必须在 1–100 之间。")
            return await self.client.journal(limit)
        return await readers[view]()

    async def record(self, payload: dict[str, Any]) -> Any:
        self._require_enabled("write") if payload.get("action", "create") in {"create", "update"} else None
        kind, action = payload.get("type"), payload.get("action", "create")
        if kind not in RECORD_PATHS or action not in {"list", "get", "create", "update"}:
            raise _invalid("不支持的记录类型或操作。")
        path = RECORD_PATHS[kind]
        if action == "list":
            return await self.client.request_json("GET", path)
        if action == "get":
            return await self.client.request_json("GET", path + "/" + _id(payload.get("id")))
        body = _body({key: value for key, value in payload.items() if key != "type"}, RECORD_FIELDS[kind])
        if kind == "sleep" and "sleepType" in payload:
            body["type"] = payload["sleepType"]
        if kind == "exercise" and "exerciseType" in payload:
            body["type"] = payload["exerciseType"]
        if kind == "life_record":
            if "recordType" in payload:
                body["type"] = payload["recordType"]
            if action == "create" and body.get("type") not in LIFE_TYPES:
                raise _invalid("recordType 不受支持。")
            if "type" in body and body["type"] not in LIFE_TYPES:
                raise _invalid("recordType 不受支持。")
        if kind == "check_in" and payload.get("source") == "inferred":
            raise _invalid("Check-in 只能依据用户表达或明确事实源创建。", "inferred_check_in_forbidden")
        if action == "create":
            return await self._write("POST", path, body, resource=kind, action="created")
        target = path + "/" + _id(payload.get("id"))
        return await self._write("PUT", target, body, confirm_path=target, resource=kind, action="updated")

    async def journal(self, payload: dict[str, Any]) -> Any:
        action = payload.get("action", "read")
        path = "/api/journal"
        if action == "read":
            return await (self.client.request_json("GET", path + "/" + _id(payload["id"]))
                          if payload.get("id") else self.client.journal(payload.get("limit", 20)))
        if action not in {"create", "update"}:
            raise _invalid("不支持的 Journal 操作。")
        self._require_enabled("write")
        body = _body(payload, {"content", "occurredAt", "images", "tags"},
                     required={"content"} if action == "create" else frozenset())
        if action == "create":
            return await self._write("POST", path, body, resource="journal", action="created")
        target = path + "/" + _id(payload.get("id"))
        return await self._write("PUT", target, body, confirm_path=target,
                                 resource="journal", action="updated")

    async def focus(self, payload: dict[str, Any]) -> Any:
        self._require_enabled("focus")
        action = payload.get("action", "current")
        base = "/api/focus"
        if action in {"current", "today", "history"}:
            return await self.client.request_json("GET", base + "/" + action,
                                                  params={"limit": payload.get("limit", 30)} if action == "history" else None)
        self._require_enabled("write")
        if action in {"start", "manual"}:
            body = _body(payload, {"mode", "title", "taskId", "plannedMinutes", "breakMinutes",
                                   "relatedTaskIds", "startedAt", "endedAt", "note"})
            if action == "start":
                body.setdefault("mode", "IRON_CURTAIN")
            return await self._write("POST", base + "/" + action, body,
                                     confirm_path=base + ("/current" if action == "start" else "/history"),
                                     resource="focus", action=action)
        target = base + "/" + _id(payload.get("id"))
        if action in {"pause", "resume", "complete", "interrupt"}:
            return await self._write("POST", target + "/" + action,
                                     {"note": payload["note"]} if action in {"complete", "interrupt"} and "note" in payload else None,
                                     confirm_path=base + ("/history" if action in {"complete", "interrupt"} else "/current"),
                                     resource="focus", action=action)
        if action == "switch_segment":
            path = target + "/segments/switch"
            method = "POST"
        elif action == "update_segment":
            path = target + "/segments/" + _id(payload.get("segmentId"))
            method = "PATCH"
        else:
            raise _invalid("不支持的 Focus 操作。")
        body = _body(payload, {"type", "title", "relatedTaskId", "note"})
        return await self._write(method, path, body, confirm_path=base + "/current",
                                 resource="focus", action=action)

    async def task(self, payload: dict[str, Any]) -> Any:
        action = payload.get("action", "list")
        if action == "list":
            return await self.client.request_json("GET", "/api/task-directions")
        if action not in {"complete", "link_direction", "unlink_direction"}:
            raise _invalid("不支持的 Task 操作。")
        self._require_enabled("write")
        source = payload.get("source")
        if source not in {"daily", "special"}:
            raise _invalid("source 必须是 daily 或 special。")
        path = "/api/task-directions/" + source + "/" + _id(payload.get("taskId"))
        if action == "complete":
            method, path, body = "POST", path + "/complete", None
        elif action == "link_direction":
            method, body = "PUT", _body(payload, {"dreamId", "goalId", "dreamMilestoneId"})
        else:
            method, body = "DELETE", None
        return await self._write(method, path, body, confirm_path="/api/task-directions",
                                 resource="task", action=action)

    async def generic(self, operation: str, payload: dict[str, Any]) -> Any:
        """Low-frequency operations stay on a closed allowlist of public endpoints."""
        self._require_enabled(operation)
        action = payload.get("action", "list")
        ident = _id(payload.get("id")) if payload.get("id") is not None else None
        if operation == "ritual":
            if action == "list": return await self.client.request_json("GET", "/api/rituals")
            if action == "get": return await self.client.request_json("GET", "/api/rituals/" + _id(payload.get("id")))
            if action == "get_execution": return await self.client.request_json("GET", "/api/ritual-executions/" + _id(payload.get("id")))
            ident = _id(payload.get("id"))
            if action == "start": path = f"/api/rituals/{ident}/start"
            elif action == "step": path = f"/api/ritual-executions/{ident}/steps/{_id(payload.get('stepId'))}"
            elif action in {"complete", "cancel"}: path = f"/api/ritual-executions/{ident}/{action}"
            else: raise _invalid("不支持的 Ritual 操作。")
            body = _body(payload, {"done", "note"}) if action == "step" else _body(payload, {"note"}) if action in {"complete", "cancel"} else None
            confirm = f"/api/ritual-executions/{ident}" if action != "start" else None
            confirm_collection = "/api/ritual-executions" if action == "start" else None
        elif operation == "dream":
            if action == "list": return await self.client.request_json("GET", "/api/dreams")
            if action == "get": return await self.client.request_json("GET", "/api/dreams/" + _id(payload.get("id")))
            ident = _id(payload.get("id"))
            if action in {"pause", "resume"}: path = f"/api/dreams/{ident}/{action}"
            elif action == "complete_goal": path = "/api/goals/" + _id(payload.get("id")) + "/complete"
            elif action == "complete_milestone": path = "/api/dream-milestones/" + _id(payload.get("id")) + "/complete"
            else: raise _invalid("不支持的 Dream 操作。")
            if action in {"complete_goal", "complete_milestone"}:
                self._require_enabled("write")
                response = await self.client.request_json("POST", path)
                confirmed = await self.client.dreams()
                return {"ok": True, "action": action, "resource": "dream", "id": ident,
                        "record": self.client.dump_for_display(confirmed), "response": response, "warnings": []}
            body, confirm = None, f"/api/dreams/{ident}"
            confirm_collection = None
        else:
            kind = payload.get("type")
            paths = {"anime": "/api/media/anime", "game": "/api/media/games", "item": "/api/media/items",
                     "anime_session": "/api/media/anime-sessions", "game_session": "/api/media/game-sessions"}
            if kind not in paths: raise _invalid("不支持的 Media 类型。")
            base = paths[kind]
            if action == "list":
                if kind.endswith("_session"):
                    parent = _id(payload.get("parentId"))
                    collection = ("/api/media/anime/" if kind == "anime_session" else "/api/media/games/") + parent + "/sessions"
                    return await self.client.request_json("GET", collection)
                return await self.client.request_json("GET", base, params={"type": payload["mediaType"]} if kind == "item" and "mediaType" in payload else None)
            if action == "get":
                if kind.endswith("_session"):
                    parent = _id(payload.get("parentId"))
                    collection = ("/api/media/anime/" if kind == "anime_session" else "/api/media/games/") + parent + "/sessions"
                    sessions = await self.client.request_json("GET", collection)
                    match = next((item for item in sessions if item.get("id") == payload.get("id")), None)
                    if match is None:
                        raise _invalid("Life HUD 中没有找到目标 Session。", "lifehud_not_found")
                    return match
                return await self.client.request_json("GET", base + "/" + _id(payload.get("id")))
            if action not in {"create", "update"}: raise _invalid("不支持的 Media 操作。")
            if action == "update": ident = _id(payload.get("id"))
            body = {k: v for k, v in payload.items() if k not in {"action", "type", "id", "mediaType", "parentId"}}
            if kind == "item" and "mediaType" in payload:
                body["type"] = payload["mediaType"]
            _body(body, set(body))  # Validate known timestamp names.
            if kind.endswith("_session") and action == "create":
                parent = _id(payload.get("parentId"))
                path = ("/api/media/anime/" if kind == "anime_session" else "/api/media/games/") + parent + "/sessions"
            else:
                path = base + ("/" + ident if action == "update" else "")
            if kind.endswith("_session"):
                parent = _id(payload.get("parentId"))
                confirm = ("/api/media/anime/" if kind == "anime_session" else "/api/media/games/") + parent + "/sessions"
            else:
                confirm = base + "/" + ident if action == "update" else None
            method = "PUT" if action == "update" else "POST"
            self._require_enabled("write")
            return await self._write(method, path, body, confirm_path=confirm, resource=kind, action=action)
        self._require_enabled("write")
        return await self._write("POST", path, body, confirm_path=confirm,
                                 confirm_collection=confirm_collection, resource=operation, action=action)
