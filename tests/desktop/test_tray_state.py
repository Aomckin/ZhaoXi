from datetime import UTC, datetime
from types import SimpleNamespace

from zhaoxi.desktop.app import DesktopHost


class FakeAgent:
    proactive = None

    def __init__(self):
        self.proactive_state = SimpleNamespace(quiet_until=None)


def make_host(tmp_path):
    settings = SimpleNamespace(
        web_host="127.0.0.1",
        web_port=4933,
        desktop_instance_path=str(tmp_path / "instance.json"),
        desktop_activation_port=4934,
        desktop_window_width=1080,
        desktop_window_height=760,
        desktop_hotkey="ctrl+alt+space",
        log_level="INFO",
    )
    return DesktopHost(settings, agent=FakeAgent())


def test_quiet_toggle_updates_shared_proactive_state(tmp_path):
    host = make_host(tmp_path)

    host._toggle_quiet()
    assert host._is_quiet()
    assert host.agent.proactive_state.quiet_until == datetime.max.replace(tzinfo=UTC)
    assert "Quiet" in host._status_text()

    host._toggle_quiet()
    assert not host._is_quiet()
