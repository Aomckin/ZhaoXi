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
        self._visible = False
        self._minimized = False
        self._show_requested = threading.Event()
        self._loaded = threading.Event()
        self._pending_delivery_id = None

    def run(self, on_closed=None, *, background: bool = False) -> None:
        try:
            import webview
        except ImportError as exc:
            raise RuntimeError(
                "Desktop 窗口依赖未安装，请运行 pip install -e .[desktop]。"
            ) from exc
        self._visible = not background
        self._window = webview.create_window(
            "朝汐 Zhaoxi",
            self.url,
            width=self.width,
            height=self.height,
            min_size=(720, 520),
            hidden=background,
        )
        self._window.events.loaded += self._on_loaded
        self._window.events.closing += self._on_closing
        self._window.events.minimized += self._on_minimized
        self._window.events.restored += self._on_restored
        self._window.events.maximized += self._on_restored
        if on_closed is not None:
            self._window.events.closed += on_closed
        webview.start(self._on_started)

    def _on_started(self) -> None:
        self._ready.set()
        if self._show_requested.is_set():
            self.show()

    def show(self) -> None:
        self._show_requested.set()
        if self._ready.is_set() and self._window is not None:
            self._window.show()
            self._window.restore()
            self._visible = True
            self._minimized = False

    def _on_loaded(self) -> None:
        self._loaded.set()
        if self._pending_delivery_id:
            self.open_delivery(self._pending_delivery_id)

    def open_delivery(self, delivery_id: str) -> None:
        import json
        self._pending_delivery_id = delivery_id
        self.show()
        if self._loaded.is_set() and self._window is not None:
            self._window.evaluate_js(f"openDelivery({json.dumps(delivery_id)})")
            self._pending_delivery_id = None

    def toggle(self) -> None:
        if self._ready.is_set() and self._visible and not self._minimized:
            self.hide()
        else:
            self.show()

    def _on_minimized(self) -> None:
        self._minimized = True

    def _on_restored(self) -> None:
        self._minimized = False

    def hide(self) -> None:
        self._show_requested.clear()
        if self._window is not None:
            self._window.hide()
            self._visible = False

    def destroy(self) -> None:
        if self._window is not None:
            self._allow_close = True
            self._window.destroy()

    def _on_closing(self) -> bool:
        if self._allow_close:
            return True
        self.hide()
        return False
