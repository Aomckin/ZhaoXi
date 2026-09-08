"""Read-only world sensor contract and conservative local activity probe."""
import sys
from datetime import datetime
from typing import Protocol
from zhaoxi.proactive.models import ProactiveEvent


class WorldSensor(Protocol):
    healthy: bool
    context: str

    async def collect(self, now: datetime) -> list[ProactiveEvent]: ...


def computer_active():
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        from ctypes import wintypes
        class LastInput(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.UINT), ('dwTime', wintypes.DWORD)]
        info = LastInput()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return False
        elapsed = (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xffffffff
        return elapsed < 5 * 60 * 1000
    except Exception:
        return False

