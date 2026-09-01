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
