"""Windows input hooks retaining only counts and transient mouse coordinates."""
import ctypes
from ctypes import wintypes as w
from threading import Thread, Event
import sys


WM_MOUSEMOVE = 0x0200


class LowLevelMouseEvent(ctypes.Structure):
    _fields_ = [
        ('pt', w.POINT),
        ('mouseData', w.DWORD),
        ('flags', w.DWORD),
        ('time', w.DWORD),
        ('dwExtraInfo', ctypes.c_void_p),
    ]


class InputHooks:
    def __init__(self, counters):
        self.counters = counters
        self.thread = None
        self.thread_id = None
        self.ready = Event()
        self.healthy = False

    def start(self):
        if sys.platform != 'win32':
            return
        self.thread = Thread(target=self._run, name='zhaoxi-input-counts', daemon=True)
        self.thread.start()
        self.ready.wait(2)

    def _run(self):
        user = ctypes.WinDLL('user32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, w.WPARAM, w.LPARAM)
        user.SetWindowsHookExW.argtypes = [ctypes.c_int, callback_type, w.HINSTANCE, w.DWORD]
        user.SetWindowsHookExW.restype = w.HANDLE
        user.CallNextHookEx.argtypes = [w.HANDLE, ctypes.c_int, w.WPARAM, w.LPARAM]
        user.CallNextHookEx.restype = ctypes.c_ssize_t
        user.UnhookWindowsHookEx.argtypes = [w.HANDLE]
        user.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
        user.PeekMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
        user.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
        user.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
        user.DispatchMessageW.restype = ctypes.c_ssize_t
        kernel.GetModuleHandleW.argtypes = [w.LPCWSTR]
        kernel.GetModuleHandleW.restype = w.HMODULE
        kernel.GetCurrentThreadId.restype = w.DWORD
        self.thread_id = kernel.GetCurrentThreadId()
        callbacks, handles = [], []
        try:
            # Force creation of the message queue before allowing shutdown.
            message = w.MSG()
            user.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            for hook_id, channel in ((13, 'keyboard'), (14, 'mouse')):
                def callback(code, message_id, payload, channel=channel):
                    if code >= 0:
                        if channel == 'keyboard':
                            self.counters.count(channel)
                        elif int(message_id) == WM_MOUSEMOVE:
                            event = ctypes.cast(payload, ctypes.POINTER(LowLevelMouseEvent)).contents
                            self.counters.mouse_move(event.pt.x, event.pt.y)
                        else:
                            # Clicks, wheel movement and other explicit mouse actions.
                            self.counters.count(channel)
                    return user.CallNextHookEx(None, code, message_id, payload)
                handler = callback_type(callback)
                callbacks.append(handler)
                handle = user.SetWindowsHookExW(hook_id, handler, kernel.GetModuleHandleW(None), 0)
                if not handle:
                    return
                handles.append(handle)
            self.healthy = True
            self.ready.set()
            while user.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user.TranslateMessage(ctypes.byref(message))
                user.DispatchMessageW(ctypes.byref(message))
        finally:
            self.healthy = False
            self.ready.set()
            for handle in handles:
                user.UnhookWindowsHookEx(handle)

    def close(self):
        if self.thread_id:
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
        if self.thread:
            self.thread.join(2)
