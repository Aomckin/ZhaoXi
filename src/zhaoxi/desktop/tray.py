"""System tray adapter with only bounded Presence actions."""

from __future__ import annotations

from collections.abc import Callable


class TrayIcon:
    def __init__(
        self,
        *,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
        on_companion: Callable[[], None] | None = None,
        on_hide: Callable[[], None] | None = None,
        on_settings: Callable[[], None] | None = None,
        on_toggle_quiet: Callable[[], None] | None = None,
        is_quiet: Callable[[], bool] | None = None,
        status_text: Callable[[], str] | None = None,
    ) -> None:
        self.on_show = on_show
        self.on_companion = on_companion or on_show
        self.on_hide = on_hide or (lambda: None)
        self.on_settings = on_settings or on_show
        self.on_quit = on_quit
        self.on_toggle_quiet = on_toggle_quiet or (lambda: None)
        self.is_quiet = is_quiet or (lambda: False)
        self.status_text = status_text or (lambda: "状态：运行中")
        self._icon = None

    def start(self) -> None:
        try:
            import pystray
            from PIL import Image
            from pathlib import Path
        except ImportError as exc:
            raise RuntimeError("托盘依赖未安装，请运行 pip install -e .[desktop]。") from exc
        image = Image.open(Path(__file__).parents[1] / "web/static/zhaoxi.png")
        self._icon = pystray.Icon(
            "zhaoxi",
            image,
            "朝汐 Zhaoxi",
            pystray.Menu(
                pystray.MenuItem("打开朝汐", lambda *_: self.on_show(), default=True),
                pystray.MenuItem("切换陪伴模式", lambda *_: self.on_companion()),
                pystray.MenuItem("隐藏朝汐", lambda *_: self.on_hide()),
                pystray.MenuItem("设置", lambda *_: self.on_settings()),
                pystray.MenuItem(lambda _: self.status_text(), None, enabled=False),
                pystray.MenuItem(
                    "Quiet Mode",
                    lambda *_: self._toggle_quiet(),
                    checked=lambda _: self.is_quiet(),
                ),
                pystray.MenuItem("退出朝汐", lambda *_: self.on_quit()),
            ),
        )
        self._icon.run_detached()

    def _toggle_quiet(self) -> None:
        self.on_toggle_quiet()
        if self._icon is not None:
            self._icon.update_menu()

    def notify(self, title: str, message: str) -> None:
        if self._icon is not None:
            self._icon.notify(message[:256], title[:64])

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
            self._icon = None
