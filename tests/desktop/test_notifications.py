from datetime import UTC, datetime

from zhaoxi.desktop.notifications import DesktopNotificationSink
from zhaoxi.proactive import (
    Delivery,
    DeliveryStatus,
    InboxNotificationSink,
    InMemoryProactiveStore,
    Priority,
)


async def test_desktop_sink_persists_then_notifies_notice():
    store = InMemoryProactiveStore()
    calls = []
    sink = DesktopNotificationSink(
        InboxNotificationSink(store),
        lambda title, body, delivery_id: calls.append((title, body, delivery_id)),
    )
    delivery = Delivery(
        event_id="event-1",
        subscription_id="subscription-1",
        priority=Priority.NOTICE,
        content="该休息一下了",
    )

    result = await sink.deliver(delivery, datetime.now(UTC))

    assert result.status is DeliveryStatus.DELIVERED
    assert calls == [("朝汐提醒", "该休息一下了", result.delivery_id)]
    assert (await store.list_deliveries())[0].delivery_id == result.delivery_id


async def test_info_stays_in_inbox_without_desktop_popup():
    store = InMemoryProactiveStore()
    calls = []
    sink = DesktopNotificationSink(InboxNotificationSink(store), lambda *args: calls.append(args))
    delivery = Delivery(
        event_id="event-2",
        subscription_id="subscription-1",
        priority=Priority.INFO,
        content="普通信息",
    )

    await sink.deliver(delivery, datetime.now(UTC))

    assert calls == []
    assert len(await store.list_deliveries()) == 1


def test_toast_activation_waits_for_page_load():
    from unittest.mock import Mock
    from zhaoxi.desktop.window import DesktopWindow
    window = DesktopWindow('http://localhost', width=1000, height=700)
    native = Mock()
    window._window = native
    window.open_delivery('delivery-123')
    native.evaluate_js.assert_not_called()
    window._on_loaded()
    native.evaluate_js.assert_called_once_with('openDelivery("delivery-123")')
    assert window._pending_delivery_id is None
