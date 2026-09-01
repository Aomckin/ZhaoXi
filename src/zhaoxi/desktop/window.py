"""pywebview-backed window that reuses the local Web shell."""

from __future__ import annotations

import threading


class DesktopWindow:
    def __init__(self, url: str, *, width: int, height: int) -> None:
        self.url = url
        self.width = width
        self.height = height
        self._window = None
        self._ready = threading.Event()
        self._allow_close = False

    def run(self, on_closed=None) -> None:
        try:
            import webview
        except ImportError as exc:
            raise RuntimeError(
                "Desktop 窗口依赖未安装，请运行 pip install -e .[desktop]。"
            ) from exc
        self._window = webview.create_window(
            "朝汐 Zhaoxi",
            self.url,
            width=self.width,
            height=self.height,
            min_size=(720, 520),
        )
        self._window.events.closing += self._on_closing
        if on_closed is not None:
            self._window.events.closed += on_closed
        self._ready.set()
        webview.start()

    def show(self) -> None:
        if self._window is not None:
            self._window.show()
            self._window.restore()

    def hide(self) -> None:
        if self._window is not None:
            self._window.hide()

    def destroy(self) -> None:
        if self._window is not None:
            self._allow_close = True
            self._window.destroy()

    def _on_closing(self) -> bool:
        if self._allow_close:
            return True
        self.hide()
        return False
