"""Desktop notification sink layered on the durable local inbox."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from zhaoxi.proactive.models import Delivery, Priority
from zhaoxi.proactive.notifications import NotificationSink


class DesktopNotificationSink(NotificationSink):
    """Persist through another sink, then render eligible desktop notifications."""

    def __init__(
        self,
        durable_sink: NotificationSink,
        notifier: Callable[[str, str, str], None],
    ) -> None:
        self.durable_sink = durable_sink
        self.notifier = notifier

    async def deliver(self, delivery: Delivery, now: datetime) -> Delivery:
        delivered = await self.durable_sink.deliver(delivery, now)
        if delivered is not delivery:
            return delivered
        if delivered.priority is not Priority.INFO:
            title = {
                Priority.NOTICE: "朝汐提醒",
                Priority.IMPORTANT: "朝汐 · 重要提醒",
                Priority.URGENT: "朝汐 · 紧急提醒",
            }[delivered.priority]
            self.notifier(title, delivered.content[:256], delivered.delivery_id)
        return delivered


class WindowsToastNotifier:
    """Interactive Windows toast that routes activation back to Desktop Host."""

    def __init__(self, on_open: Callable[[str], None]) -> None:
        self.on_open = on_open
        try:
            from windows_toasts import WindowsToaster
        except ImportError as exc:
            raise RuntimeError(
                "Windows Toast 依赖未安装，请运行 pip install -e .[desktop]。"
            ) from exc
        self._toaster = WindowsToaster("朝汐 Zhaoxi")

    def show(self, title: str, message: str, delivery_id: str) -> None:
        from windows_toasts import Toast

        toast = Toast([title[:64], message[:256]])
        toast.on_activated = lambda _: self.on_open(delivery_id)
        self._toaster.show_toast(toast)

class NativeNotifier:
    """Bounded transient WinForms card; Windows Toast is a lazy fallback."""
    def __init__(self, window, on_open, *, system_mode=False):
        self.window, self.on_open = window, on_open
        self.system_mode = system_mode
        self._card = None
        self._timer = None
        self._fallback = None

    def show(self, title, message, delivery_id):
        import logging
        if self.window.focused():
            return
        try:
            if self.system_mode or not self.window._native:
                raise RuntimeError('system notification fallback')
            from zhaoxi.desktop.native import invoke
            def create(parent):
                from System.Drawing import Color, Point, Size
                from System.Windows.Forms import Form, FormBorderStyle, Label, Button, Screen, Timer, FormStartPosition
                if self._card:
                    self._card.Close()
                if self._timer:
                    self._timer.Stop()
                    self._timer.Dispose()
                card = Form()
                card.Text = '朝汐 · 通知'
                card.FormBorderStyle = getattr(FormBorderStyle, 'None')
                card.StartPosition = FormStartPosition.Manual
                card.ShowInTaskbar = False
                card.BackColor = Color.FromArgb(248,241,218)
                area = Screen.FromControl(parent).WorkingArea
                card.Size = Size(min(360,area.Width), min(170,area.Height))
                card.Location = Point(area.Right-card.Width-8,area.Bottom-card.Height-8)
                heading, body, close = Label(), Label(), Button()
                heading.Text, body.Text, close.Text = title, message, '×'
                heading.Location, heading.Size = Point(16,12), Size(card.Width-70,28)
                body.Location, body.Size = Point(16,44), Size(card.Width-32,110)
                close.Location, close.Size = Point(card.Width-42,8), Size(32,28)
                def activate(*_):
                    card.Close()
                    import threading
                    threading.Thread(target=self.on_open,args=(delivery_id,),daemon=True).start()
                heading.Click += activate
                body.Click += activate
                close.Click += lambda *_: card.Close()
                for control in (heading,body,close):
                    card.Controls.Add(control)
                timer = Timer()
                timer.Interval = 8000
                timer.Tick += lambda *_: card.Close()
                def closed(*_):
                    timer.Stop()
                    timer.Dispose()
                    if self._card == card:
                        self._card = self._timer = None
                    card.Dispose()
                card.FormClosed += closed
                # Show without activation, then topmost without stealing focus.
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
                user32.SetWindowPos.argtypes = [wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
                handle = card.Handle.ToInt64()
                user32.ShowWindow(handle, 4)  # SW_SHOWNOACTIVATE
                user32.SetWindowPos(handle, -1, 0,0,0,0, 0x0013) # NOMOVE | NOSIZE | NOACTIVATE
                self._card, self._timer = card, timer
                timer.Start()
            invoke(self.window._window, create)
        except Exception:
            logging.getLogger('DESKTOP').warning('Native notification unavailable; using Windows Toast', exc_info=True)
            try:
                if self._fallback is None:
                    self._fallback = WindowsToastNotifier(self.on_open)
                self._fallback.show(title,message,delivery_id)
            except Exception:
                logging.getLogger('DESKTOP').exception('Notification unavailable; delivery remains in inbox')

    def stop(self):
        if self.window._native and self._card:
            from zhaoxi.desktop.native import invoke
            invoke(self.window._window, lambda _: self._card.Close() if self._card else None)
