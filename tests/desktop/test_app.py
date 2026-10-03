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


def test_dashboard_and_tray_settings_open_system_browser(tmp_path, monkeypatch):
    from zhaoxi.desktop.window import ShellBridge
    settings=SimpleNamespace(web_host="127.0.0.1",web_port=4913,desktop_instance_path=str(tmp_path/"instance.json"),
        desktop_activation_port=0,desktop_window_width=1080,desktop_window_height=760,
        desktop_hotkey="ctrl+alt+space",log_level="INFO")
    host=DesktopHost(settings,agent=FakeAgent())
    opened=[]
    monkeypatch.setattr("webbrowser.open",lambda url,**kwargs:opened.append(url) or True)
    assert ShellBridge(host.window).command("open_dashboard", "memory")=={"opened":True}
    host.tray.on_settings()
    assert opened==["http://127.0.0.1:4913/dashboard#memory","http://127.0.0.1:4913/dashboard#settings"]
    assert host.window.mode.value=="main" and not host.window._visible
    host.open_dashboard("https://external.test")
    assert opened[-1]=="http://127.0.0.1:4913/dashboard#overview"
