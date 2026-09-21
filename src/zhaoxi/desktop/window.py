"""One desktop window, one WebView, two presentation modes."""
from __future__ import annotations

import json
import logging
import threading
from enum import StrEnum
from pathlib import Path
import sys

logger = logging.getLogger('DESKTOP')


class WindowMode(StrEnum):
    MAIN = 'main'
    COMPANION = 'companion'


class ShellBridge:
    def __init__(self, owner):
        self._owner = owner

    def command(self, action, value=None):
        owner = self._owner
        if action == 'state':
            return owner.state()
        if action == 'mode':
            owner.switch_mode(value)
        elif action == 'hide':
            owner.hide()
        elif action == 'minimize':
            owner._window.minimize()
        elif action == 'maximize':
            owner.title_double_click()
        elif action == 'topmost':
            owner.set_topmost(bool(value))
        elif action == 'gesture':
            owner._native.gesture(value)
        return owner.state()


class DesktopWindow:
    def __init__(self, url: str, *, width: int, height: int, geometry_path=None) -> None:
        self.url, self.width, self.height = url, width, height
        self._window = None
        self._native = None
        self.on_show = lambda: None
        self._ready = threading.Event()
        self._allow_close = False
        self._visible = False
        self._minimized = False
        self._show_requested = threading.Event()
        self._loaded = threading.Event()
        self._pending_delivery_id = None
        self._lock = threading.RLock()
        self.mode = WindowMode.MAIN
        self._topmost = False
        self.native_topmost_calls = 0
        self.geometry_path = Path(geometry_path) if geometry_path else None
        self.geometries = {'main': dict(x=100,y=100,width=width,height=height,maximized=False),
                           'companion': dict(x=100,y=100,width=390,height=480,topmost=False)}
        if self.geometry_path:
            try:
                saved = json.loads(self.geometry_path.read_text(encoding='utf-8'))
                for mode, default in self.geometries.items():
                    value = saved.get(mode, {})
                    if all(type(value.get(k)) is int for k in ('x','y','width','height')) and 0 < value['width'] <= 16000 and 0 < value['height'] <= 16000:
                        default.update({k:value[k] for k in default if k in value})
            except (OSError, ValueError, TypeError, AttributeError):
                pass

    def state(self):
        return dict(mode=self.mode.value, topmost=self._topmost, native_topmost_calls=self.native_topmost_calls)

    def _save(self):
        if self._native:
            geometry = self._native.snapshot()
            if self._minimized:
                geometry.pop("maximized", None)
            self.geometries[self.mode.value].update(geometry)
        if self.geometry_path:
            self.geometry_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.geometry_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.geometries), encoding='utf-8')
            temporary.replace(self.geometry_path)

    def switch_mode(self, mode):
        mode = WindowMode(mode)
        with self._lock:
            if mode == self.mode:
                return
            self._save()
            self.mode = mode
            if self._native:
                self._native.apply(self.geometries[mode.value], mode.value)
            self.set_topmost(bool(self.geometries['companion'].get('topmost')) if mode == WindowMode.COMPANION else False, remember=False)
            self._publish()

    def _publish(self):
        if self._loaded.is_set() and self._window:
            self._window.evaluate_js(f'window.desktopShellState && window.desktopShellState({json.dumps(self.state())})')

    def set_topmost(self, value, *, remember=True):
        with self._lock:
            value = bool(value) and self.mode == WindowMode.COMPANION
            old = self._topmost
            if old != value and self._native:
                self._native.topmost(value)
                self.native_topmost_calls += 1
                self._topmost = value
            if remember and self.mode == WindowMode.COMPANION:
                self.geometries['companion']['topmost'] = value
                self._save()
            logger.info('topmost toggle requested old=%s new=%s native_call_count=%s', old, self._topmost, self.native_topmost_calls)
            self._publish()

    def title_double_click(self):
        if self.mode == WindowMode.COMPANION:
            self.switch_mode(WindowMode.MAIN)
        elif self._native:
            self._native.maximize()

    def focused(self):
        return bool(self._native and self._visible and not self._minimized and self._native.focused())

    def show_main(self):
        self.switch_mode(WindowMode.MAIN)
        self.show()

    def show_companion(self):
        self.switch_mode(WindowMode.COMPANION)
        self.show()

    def show_settings(self):
        self.show_main()
        if self._loaded.is_set():
            self._window.evaluate_js('window.desktopOpenSettings && window.desktopOpenSettings()')

    def run(self, on_closed=None, *, background=False):
        import webview
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Zhaoxi.Desktop')
        self._visible = not background
        self._window = webview.create_window('朝汐 Zhaoxi', self.url, width=self.width, height=self.height,
            min_size=(300,320), hidden=background, frameless=True, easy_drag=False, resizable=True,
            js_api=ShellBridge(self))
        self._window.events.loaded += self._on_loaded
        self._window.events.closing += self._on_closing
        self._window.events.minimized += self._on_minimized
        self._window.events.restored += self._on_restored
        self._window.events.maximized += self._on_restored
        if on_closed:
            self._window.events.closed += on_closed
        webview.start(self._on_started, icon=str(Path(__file__).parents[1] / 'web/static/zhaoxi.ico'))

    def _on_started(self):
        if not self._window.events.shown.wait(15):
            raise RuntimeError("Desktop native window initialization timed out")
        from zhaoxi.desktop.native import WindowsFrame
        self._native = WindowsFrame(self._window)
        self._native.apply(self.geometries[self.mode.value], self.mode.value)
        if self.mode == WindowMode.COMPANION:
            self.set_topmost(self.geometries['companion'].get('topmost',False), remember=False)
        self._ready.set()
        self._publish()
        if self._visible:
            self.on_show()
        if self._show_requested.is_set():
            self.show()

    def show(self):
        self.on_show()
        self._show_requested.set()
        if self._ready.is_set() and self._window:
            self._window.show()
            if self._minimized:
                self._window.restore()
            self._visible, self._minimized = True, False

    def _on_loaded(self):
        self._loaded.set()
        if self._native:
            self._publish()
        if self._pending_delivery_id:
            self.open_delivery(self._pending_delivery_id)

    def open_delivery(self, delivery_id):
        self._pending_delivery_id = delivery_id
        self.show()
        if self._loaded.is_set() and self._window:
            self._window.evaluate_js(f'openDelivery({json.dumps(delivery_id)})')
            self._pending_delivery_id = None

    def _toggle_mode(self, mode: WindowMode):
        if self._ready.is_set() and self._visible and not self._minimized and self.mode == mode:
            self.hide()
        else:
            (self.show_main if mode == WindowMode.MAIN else self.show_companion)()

    def toggle(self):
        """Toggle the normal window; kept as the primary hotkey callback."""
        self._toggle_mode(WindowMode.MAIN)

    def toggle_companion(self):
        self._toggle_mode(WindowMode.COMPANION)

    def _on_minimized(self):
        self._minimized = True

    def _on_restored(self):
        self._minimized = False

    def hide(self):
        self._show_requested.clear()
        with self._lock:
            self._save()
        if self._window:
            self._window.hide()
            self._visible = False

    def destroy(self):
        with self._lock:
            self._save()
        if self._window:
            self._allow_close = True
            self._window.destroy()

    def _on_closing(self):
        if self._allow_close:
            return True
        self.hide()
        return False
