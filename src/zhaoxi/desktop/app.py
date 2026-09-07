"""Desktop Presence lifecycle around the existing local Web application."""

from __future__ import annotations

import logging
import secrets
import socket
import threading
import time
from datetime import UTC, datetime

from zhaoxi.config.settings import Settings
from zhaoxi.desktop.hotkey import GlobalHotkey
from zhaoxi.desktop.instance import InstanceCoordinator
from zhaoxi.desktop.notifications import DesktopNotificationSink, WindowsToastNotifier
from zhaoxi.desktop.tray import TrayIcon
from zhaoxi.desktop.window import DesktopWindow
from zhaoxi.proactive.notifications import InboxNotificationSink
from zhaoxi.web.app import create_app
from zhaoxi.errors import ZhaoxiError
from zhaoxi.interfaces.setup import StartupUnavailableAgent
from zhaoxi.reliability.startup import startup_diagnostics

logger = logging.getLogger("DESKTOP")


def build_voice_runtime(settings: Settings):
    if not settings.voice_enabled:
        return None
    if settings.stt_provider != "openai-compatible":
        raise RuntimeError("Voice 已启用，但尚未配置可用的 STT Provider。")
    if settings.tts_provider != "windows":
        raise RuntimeError("Voice 已启用，但尚未配置可用的 TTS Provider。")
    from zhaoxi.voice.models import AudioSpec
    from zhaoxi.voice.recorder_sounddevice import SoundDeviceRecorder
    from zhaoxi.voice.runtime import VoiceRuntime
    from zhaoxi.voice.stt_openai import OpenAICompatibleSTT
    from zhaoxi.voice.temp_store import VoiceTempStore
    from zhaoxi.voice.tts_windows import WindowsTextToSpeech

    store = VoiceTempStore(settings.voice_temp_dir)
    store.cleanup_orphans()
    spec = AudioSpec(
        max_seconds=settings.voice_max_seconds,
        max_bytes=settings.voice_max_bytes,
    )
    return VoiceRuntime(
        recorder=SoundDeviceRecorder(store),
        stt=OpenAICompatibleSTT(
            base_url=settings.stt_base_url,
            api_key=settings.stt_api_key,
            model=settings.stt_model,
            timeout_seconds=settings.stt_timeout_seconds,
        ),
        tts=WindowsTextToSpeech(
            voice=settings.tts_voice,
            rate=settings.tts_rate,
            volume=settings.tts_volume,
        ),
        temp_store=store,
        spec=spec,
        language=settings.voice_language,
    )


class DesktopHost:
    def __init__(self, settings: Settings, *, agent=None) -> None:
        self.settings = settings
        self.api_token = secrets.token_urlsafe(32)
        self.url = f"http://{settings.web_host}:{settings.web_port}#token={self.api_token}"
        self.instance = InstanceCoordinator(
            settings.desktop_instance_path,
            settings.desktop_activation_port,
        )
        self.window = DesktopWindow(
            self.url,
            width=settings.desktop_window_width,
            height=settings.desktop_window_height,
        )
        self.tray = TrayIcon(
            on_show=self.window.show,
            on_quit=self.stop,
            on_toggle_quiet=self._toggle_quiet,
            is_quiet=self._is_quiet,
            status_text=self._status_text,
        )
        self.hotkey = GlobalHotkey(settings.desktop_hotkey, self.window.toggle)
        self.notifier = WindowsToastNotifier(self._open_delivery)
        self.agent = agent
        self.voice = None
        self._server = None
        self._server_thread: threading.Thread | None = None
        self._stopping = threading.Event()

    def _initialize_core(self) -> None:
        settings = self.settings
        agent = self.agent
        if agent is None:
            from zhaoxi.cli import build_agent

            try:
                agent = build_agent(settings)
            except ZhaoxiError as exc:
                agent = StartupUnavailableAgent(startup_diagnostics(settings), str(exc))
        self.agent = agent
        self.voice = None
        heartbeat = getattr(agent, "proactive_heartbeat", None)
        if heartbeat is not None:
            from zhaoxi.desktop.presence import DesktopPresenceSensor
            heartbeat.presence = DesktopPresenceSensor()
            self.window.on_show = heartbeat.state.interaction.window_opened.set
        try:
            self.voice = build_voice_runtime(settings)
        except Exception as exc:
            logger.warning("voice disabled after initialization failure: %s", exc)
        if getattr(self.agent, "proactive", None) is not None:
            store = self.agent.proactive.store
            self.agent.proactive.sink = DesktopNotificationSink(
                InboxNotificationSink(store),
                self.notifier.show,
            )
    def run(self, *, background: bool = False) -> bool:
        if not self.instance.acquire(self.window.show):
            return False
        try:
            self._initialize_core()
            self._start_server()
            self.tray.start()
            try:
                self.hotkey.start()
            except RuntimeError as exc:
                logger.warning("hotkey unavailable: %s", exc)
            self.window.run(on_closed=self._on_window_closed, background=background)
            return True
        finally:
            self.stop()

    def _start_server(self) -> None:
        import uvicorn

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind((self.settings.web_host, self.settings.web_port))
        except OSError as exc:
            raise RuntimeError(
                f"本地端口 {self.settings.web_host}:{self.settings.web_port} 已被占用；"
                "请关闭已有 Web 实例或修改 ZHAOXI_WEB_PORT。"
            ) from exc
        finally:
            probe.close()

        config = uvicorn.Config(
            create_app(
                agent=self.agent,
                settings=self.settings,
                api_token=self.api_token,
                voice_runtime=self.voice,
            ),
            host=self.settings.web_host,
            port=self.settings.web_port,
            log_level=self.settings.log_level.lower(),
            log_config=None,
        )
        self._server = uvicorn.Server(config)
        self._server_thread = threading.Thread(
            target=self._server.run,
            name="zhaoxi-desktop-web",
            daemon=True,
        )
        self._server_thread.start()
        deadline = time.monotonic() + 5
        while not self._server.started and self._server_thread.is_alive():
            if time.monotonic() >= deadline:
                raise RuntimeError("本地 Desktop 服务启动超时。")
            time.sleep(0.01)
        if not self._server_thread.is_alive():
            raise RuntimeError("本地 Desktop 服务启动失败。")

    def _on_window_closed(self) -> None:
        if not self._stopping.is_set():
            logger.info("desktop window closed; core remains available from tray")

    def _open_delivery(self, delivery_id: str) -> None:
        logger.info("desktop notification opened delivery_id=%s", delivery_id)
        self.window.open_delivery(delivery_id)

    def _is_quiet(self) -> bool:
        state = getattr(self.agent, "proactive_state", None)
        return bool(state and state.quiet_until and state.quiet_until > datetime.now(UTC))

    def _toggle_quiet(self) -> None:
        state = getattr(self.agent, "proactive_state", None)
        if state is None:
            return
        state.quiet_until = None if self._is_quiet() else datetime.max.replace(tzinfo=UTC)
        logger.info("desktop quiet mode enabled=%s", self._is_quiet())

    def _status_text(self) -> str:
        state = getattr(self.agent, "proactive_state", None)
        if state is None:
            return "状态：运行中 · Proactive 关闭"
        return "状态：运行中 · Quiet" if self._is_quiet() else "状态：运行中"

    def stop(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        self.hotkey.stop()
        self.tray.stop()
        if self._server is not None:
            self._server.should_exit = True
        if self._server_thread is not None:
            self._server_thread.join(timeout=5)
        self.instance.close()
        self.window.destroy()


def run_desktop(settings: Settings | None = None, *, background: bool = False) -> None:
    # pythonw has no standard streams; optional GUI libraries may still write.
    import os
    import sys

    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    configured = settings or Settings()
    from zhaoxi.config.logging import configure_logging

    configure_logging(
        configured.log_level, path=configured.log_path,
        max_bytes=configured.log_max_bytes, backup_count=configured.log_backup_count,
    )
    DesktopHost(configured).run(background=background)
