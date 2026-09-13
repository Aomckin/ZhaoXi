"""Windows UI-thread adapter. No polling and no additional WebView."""
from __future__ import annotations


def invoke(window, action):
    from System import Action
    form = window.native
    result = []
    errors = []
    def run():
        try:
            result.append(action(form))
        except Exception as exc:
            errors.append(exc)
    if form.InvokeRequired:
        form.Invoke(Action(run))
    else:
        run()
    if errors:
        raise errors[0]
    return result[0] if result else None


class WindowsFrame:
    def __init__(self, window):
        self.window = window
        self.mode = 'main'
        self._subclass = None
        self._install_border()

    def _install_border(self):
        def install(form):
            import ctypes
            from ctypes import wintypes
            user32, comctl32 = ctypes.windll.user32, ctypes.windll.comctl32
            hwnd = form.Handle.ToInt64()
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
            comctl32.DefSubclassProc.argtypes = [wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
            comctl32.DefSubclassProc.restype = ctypes.c_ssize_t
            comctl32.SetWindowSubclass.argtypes = [wintypes.HWND,callback_type,ctypes.c_size_t,ctypes.c_size_t]
            comctl32.RemoveWindowSubclass.argtypes = [wintypes.HWND,callback_type,ctypes.c_size_t]
            user32.GetWindowRect.argtypes = [wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
            user32.IsZoomed.argtypes = [wintypes.HWND]
            user32.GetDpiForWindow.argtypes = [wintypes.HWND]
            user32.GetWindowLongW.argtypes = [wintypes.HWND,ctypes.c_int]
            user32.SetWindowLongW.argtypes = [wintypes.HWND,ctypes.c_int,ctypes.c_long]
            user32.SetWindowPos.argtypes = [wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
            def procedure(handle, message, wparam, lparam, subclass_id, reference):
                if message == 0x0083:  # WM_NCCALCSIZE: keep the custom chrome client area.
                    return 0
                if message == 0x0084 and not user32.IsZoomed(handle):
                    rect = wintypes.RECT()
                    user32.GetWindowRect(handle,ctypes.byref(rect))
                    x, y = ctypes.c_short(lparam & 0xffff).value, ctypes.c_short((lparam >> 16) & 0xffff).value
                    border = max(5,round(6 * user32.GetDpiForWindow(handle) / 96))
                    result = resize_hit_test(x,y,rect.left,rect.top,rect.right,rect.bottom,border)
                    if result:
                        return result
                if message == 0x0112 and (wparam & 0xfff0) == 0xf030 and self.mode == 'companion':
                    return 0  # Companion has no native maximize, including system commands.
                if message == 0x0082:
                    comctl32.RemoveWindowSubclass(handle,self._subclass,1)
                return comctl32.DefSubclassProc(handle,message,wparam,lparam)
            self._subclass = callback_type(procedure)
            if not comctl32.SetWindowSubclass(hwnd,self._subclass,1,0):
                raise ctypes.WinError()
            style = user32.GetWindowLongW(hwnd,-16)
            user32.SetWindowLongW(hwnd,-16,style | 0x00040000 | 0x00080000 | 0x00020000)
            user32.SetWindowPos(hwnd,None,0,0,0,0,0x0037)
        invoke(self.window, install)

    def snapshot(self):
        def read(form):
            from System.Windows.Forms import FormWindowState
            maximized = form.WindowState == FormWindowState.Maximized
            rect = form.RestoreBounds if form.WindowState != FormWindowState.Normal else form.Bounds
            return dict(x=rect.X, y=rect.Y, width=rect.Width, height=rect.Height, maximized=maximized)
        return invoke(self.window, read)

    def apply(self, geometry, mode):
        self.mode = mode
        def apply(form):
            from System.Drawing import Rectangle, Size
            from System.Windows.Forms import Screen, FormWindowState
            # Screen coordinates and WinForms bounds both use the current DPI context.
            rect = Rectangle(geometry['x'], geometry['y'], geometry['width'], geometry['height'])
            area = Screen.FromRectangle(rect).WorkingArea
            minimum = (300, 320) if mode == 'companion' else (720, 520)
            width = min(max(minimum[0], rect.Width), area.Width)
            height = min(max(minimum[1], rect.Height), area.Height)
            form.WindowState = FormWindowState.Normal
            form.MaximizedBounds = area
            form.MinimumSize = Size(min(minimum[0], area.Width), min(minimum[1], area.Height))
            form.MaximizeBox = mode == 'main'
            form.Bounds = Rectangle(max(area.Left, min(rect.X, area.Right-width)), max(area.Top, min(rect.Y, area.Bottom-height)), width, height)
            if mode == 'main' and geometry.get('maximized'):
                form.WindowState = FormWindowState.Maximized
        invoke(self.window, apply)

    def topmost(self, value):
        invoke(self.window, lambda form: setattr(form, 'TopMost', value))

    def focused(self):
        return invoke(self.window, lambda form: bool(form.ContainsFocus and form.Visible))

    def gesture(self, edge):
        edges = {'left':1, 'right':2, 'top':3, 'top-left':4, 'top-right':5, 'bottom':6, 'bottom-left':7, 'bottom-right':8}
        if edge != 'move' and edge not in edges:
            raise ValueError('Invalid resize edge')
        def begin(form):
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.SendMessageW.restype = ctypes.c_ssize_t
            user32.ReleaseCapture()
            user32.SendMessageW(form.Handle.ToInt64(), 0x0112, 0xF012 if edge == 'move' else 0xF000 + edges[edge], 0)
        invoke(self.window, begin)

    def maximize(self):
        def toggle(form):
            from System.Windows.Forms import FormWindowState
            form.WindowState = FormWindowState.Normal if form.WindowState == FormWindowState.Maximized else FormWindowState.Maximized
        invoke(self.window, toggle)


def resize_hit_test(x, y, left, top, right, bottom, border):
    """Win32 HT constants; coordinates are physical pixels, including negative monitors."""
    if not (left <= x < right and top <= y < bottom):
        return 0
    west, east = x < left + border, x >= right - border
    north, south = y < top + border, y >= bottom - border
    if north:
        return 13 if west else 14 if east else 12
    if south:
        return 16 if west else 17 if east else 15
    return 10 if west else 11 if east else 0
