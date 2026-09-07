"""Windows presence metadata only: idle duration, executable basename and geometry."""
import asyncio
import ctypes
from ctypes import wintypes as w
from pathlib import PureWindowsPath
import sys

from zhaoxi.proactive.interaction import PresenceSnapshot


def covers_monitor(window, monitor):
    return (window.left <= monitor.left and window.top <= monitor.top
            and window.right >= monitor.right and window.bottom >= monitor.bottom)


def read_presence():
    if sys.platform != "win32":
        return PresenceSnapshot(healthy=False)
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    # Explicit pointer-sized signatures are required on 64-bit Windows.
    user.GetForegroundWindow.restype = w.HWND
    user.GetShellWindow.restype = w.HWND
    user.OpenInputDesktop.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    user.OpenInputDesktop.restype = w.HANDLE
    user.GetUserObjectInformationW.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    user.CloseDesktop.argtypes = [w.HANDLE]
    user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    user.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    user.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
    user.MonitorFromWindow.restype = w.HANDLE
    user.GetMonitorInfoW.argtypes = [w.HANDLE, ctypes.c_void_p]
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.GetTickCount.restype = w.DWORD

    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", w.UINT), ("dwTime", w.DWORD)]

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT), ("rcWork", w.RECT), ("dwFlags", w.DWORD)]

    info = LastInput()
    info.cbSize = ctypes.sizeof(info)
    if not user.GetLastInputInfo(ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    idle = ((kernel.GetTickCount() - info.dwTime) & 0xffffffff) / 1000
    desktop = user.OpenInputDesktop(0, False, 0x0001)  # DESKTOP_READOBJECTS
    locked = not desktop
    if desktop:
        try:
            name = ctypes.create_unicode_buffer(256)
            needed = w.DWORD()
            locked = (not user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed))
                      or name.value.casefold() != "default")
        finally:
            user.CloseDesktop(desktop)
    # Secure/invisible desktop: do not inspect the foreground process.
    if locked:
        return PresenceSnapshot(last_input_seconds=idle, locked=True)
    hwnd = user.GetForegroundWindow()
    process, fullscreen = None, False
    if hwnd and hwnd != user.GetShellWindow():
        rect, monitor = w.RECT(), MonitorInfo()
        monitor.cbSize = ctypes.sizeof(monitor)
        handle = user.MonitorFromWindow(hwnd, 2)
        if user.GetWindowRect(hwnd, ctypes.byref(rect)) and user.GetMonitorInfoW(handle, ctypes.byref(monitor)):
            fullscreen = covers_monitor(rect, monitor.rcMonitor)
        pid = w.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel.OpenProcess(0x1000, False, pid.value)
        if handle:
            try:
                size = w.DWORD(32768)
                name = ctypes.create_unicode_buffer(size.value)
                if kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
                    process = PureWindowsPath(name.value).name
            finally:
                kernel.CloseHandle(handle)
    return PresenceSnapshot(idle, process, fullscreen, locked)


class DesktopPresenceSensor:
    def __init__(self, reader=read_presence):
        self.reader = reader

    async def sample(self):
        try:
            return await asyncio.to_thread(self.reader)
        except (OSError, AttributeError):
            return PresenceSnapshot(healthy=False)
