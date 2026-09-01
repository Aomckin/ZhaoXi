import socket
from types import SimpleNamespace

import pytest

from zhaoxi.desktop.app import DesktopHost


class FakeAgent:
    proactive = None


def test_desktop_reports_occupied_web_port(tmp_path):
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    port = occupied.getsockname()[1]
    settings = SimpleNamespace(
        web_host="127.0.0.1",
        web_port=port,
        desktop_instance_path=str(tmp_path / "instance.json"),
        desktop_activation_port=0,
        desktop_window_width=1080,
        desktop_window_height=760,
        desktop_hotkey="ctrl+alt+space",
        log_level="INFO",
    )
    host = DesktopHost(settings, agent=FakeAgent())

    try:
        with pytest.raises(RuntimeError, match="已被占用"):
            host._start_server()
    finally:
        occupied.close()
