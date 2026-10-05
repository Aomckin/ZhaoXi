"""Settings api routes with explicit application dependencies."""
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException
from zhaoxi.tools.filesystem_access import resolve_access_directories, save_filesystem_access, validate_write_subset
from .schemas import InterfaceSettingsRequest, ThinkingRequest, FilesystemAccessRequest
logger = logging.getLogger("WEB")


def _load_interface_settings(path: Path) -> InterfaceSettingsRequest:
    try:
        return InterfaceSettingsRequest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return InterfaceSettingsRequest()


def _save_interface_settings(path: Path, value: InterfaceSettingsRequest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


def _apply_request_timeout(core, *, enabled: bool, default_seconds: float) -> None:
    timeout = 120 if enabled else default_seconds
    if hasattr(core, "timeout_seconds"):
        core.timeout_seconds = timeout
    provider = getattr(core, "provider", None)
    providers = getattr(provider, "providers", [provider] if provider is not None else [])
    for item in providers:
        if hasattr(item, "timeout"):
            item.timeout = timeout


def _apply_force_fast_chat(core, *, enabled: bool) -> None:
    cognitive = getattr(core, "cognitive", None)
    if cognitive is not None:
        cognitive.force_fast_chat = enabled


def settings_api_router(core, configured, events):
    router = APIRouter()
    interface_settings_path = Path(configured.interface_settings_path)
    filesystem_access_path = Path(configured.filesystem_access_path)

    def thinking_provider():
        provider = getattr(core, "provider", None)
        return provider.providers[0] if getattr(provider, "providers", None) else provider


    def thinking_mode() -> str:
        enabled = getattr(thinking_provider(), "thinking_enabled", None)
        if enabled is None:
            return "off"
        return "enabled" if enabled else "disabled"


    @router.get("/api/settings/thinking")
    async def thinking_settings():
        return {"mode": thinking_mode()}


    @router.put("/api/settings/thinking")
    async def change_thinking(request: ThinkingRequest):
        provider = thinking_provider()
        if not hasattr(provider, "set_thinking"):
            raise HTTPException(status_code=409, detail="模型接口尚未就绪")
        enabled = {"off": None, "disabled": False, "enabled": True}[request.mode]
        provider.set_thinking(enabled)
        return {"mode": thinking_mode()}


    @router.get("/api/settings/interface")
    async def interface_settings():
        return _load_interface_settings(interface_settings_path)


    async def persist_interface_settings(request: InterfaceSettingsRequest):
        try:
            _save_interface_settings(interface_settings_path, request)
        except OSError as exc:
            logger.warning("interface settings persistence failed type=%s", type(exc).__name__)
            raise HTTPException(status_code=500, detail="界面设置保存失败。") from exc
        _apply_request_timeout(
            core,
            enabled=request.long_wait_enabled,
            default_seconds=configured.request_timeout_seconds,
        )
        _apply_force_fast_chat(core, enabled=request.force_fast_chat)
        await events.publish({"type": "interface_settings", "settings": request.model_dump()})
        return request


    @router.put("/api/settings/interface")
    async def change_interface_settings(request: InterfaceSettingsRequest):
        return await persist_interface_settings(request)


    @router.patch("/api/settings/interface")
    async def patch_interface_settings(request: InterfaceSettingsRequest):
        saved = _load_interface_settings(interface_settings_path)
        updated = saved.model_copy(update=request.model_dump(exclude_unset=True))
        return await persist_interface_settings(updated)


    @router.put("/api/tools/filesystem-access")
    async def change_filesystem_access(body: FilesystemAccessRequest):
        try:
            read_directories = resolve_access_directories(body.read_directories)
            write_directories = resolve_access_directories(body.write_directories)
            validate_write_subset(read_directories, write_directories)
            save_filesystem_access(
                filesystem_access_path,
                read_directories=read_directories,
                write_directories=write_directories,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            logger.warning("filesystem access persistence failed type=%s", type(exc).__name__)
            raise HTTPException(status_code=500, detail="允许目录保存失败。") from exc
        return {
            "read_directories": read_directories,
            "write_directories": write_directories,
            "restart_required": True,
            "message": "已保存，重启 Core 后生效。",
        }


    return router
