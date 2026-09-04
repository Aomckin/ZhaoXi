"""Windows global hotkey adapter using RegisterHotKey without key logging."""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes


_MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "win": 0x0008}
_KEYS = {
    "space": 0x20,
    **{chr(code).lower(): code for code in range(0x41, 0x5B)},
    **{f"numpad{digit}": 0x60 + digit for digit in range(10)},
}


def parse_hotkey(value: str) -> tuple[int, int]:
    parts = [part.strip().lower() for part in value.split("+") if part.strip()]
    if len(parts) < 2:
        raise ValueError("快捷键必须包含修饰键和按键")
    modifiers = 0
    for part in parts[:-1]:
        if part not in _MODIFIERS:
            raise ValueError(f"不支持的快捷键修饰键：{part}")
        modifiers |= _MODIFIERS[part]
    key = _KEYS.get(parts[-1])
    if key is None:
        raise ValueError(f"不支持的快捷键按键：{parts[-1]}")
    return modifiers, key


class GlobalHotkey:
    def __init__(self, hotkey: str, callback: Callable[[], None]) -> None:
        self.modifiers, self.key = parse_hotkey(hotkey)
        self.hotkey = "+".join(part.strip().lower() for part in hotkey.split("+") if part.strip())
        self.callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._error: str | None = None

    def start(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("全局快捷键当前只支持 Windows。")
        self._thread = threading.Thread(target=self._run, name="zhaoxi-hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2)
        if self._error:
            raise RuntimeError(self._error)

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = int(kernel32.GetCurrentThreadId())
        if not user32.RegisterHotKey(None, 1, self.modifiers, self.key):
            self._error = f"全局快捷键 {self.hotkey} 注册失败，可能已被其他程序占用。"
            self._ready.set()
            return
        self._ready.set()
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == 0x0312:
                self.callback()
        user32.UnregisterHotKey(None, 1)

    def stop(self) -> None:
        if self._thread_id is not None and sys.platform == "win32":
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None
