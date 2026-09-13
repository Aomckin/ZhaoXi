import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zhaoxi.config.settings import Settings
from zhaoxi.desktop.hotkey import GlobalHotkey, parse_hotkey


@pytest.mark.parametrize('value', ['ctrl+alt+numpad0', ' CTRL + Alt + NumPad0 '])
def test_numpad_zero(value):
    assert parse_hotkey(value) == (0x0002 | 0x0001, 0x60)


@pytest.mark.parametrize('digit', range(10))
def test_numpad_digits(digit):
    assert parse_hotkey(f'ctrl+alt+numpad{digit}') == (3, 0x60 + digit)


@pytest.mark.parametrize('key', ['0', 'numpad10', 'banana', 'mouse1'])
def test_invalid_or_main_row_digit_is_not_numpad(key):
    with pytest.raises(ValueError, match='不支持'):
        parse_hotkey(f'ctrl+alt+{key}')


@pytest.mark.parametrize('key,code', [('space', 0x20), ('a', 0x41), ('Z', 0x5A)])
def test_existing_keys_remain_supported(key, code):
    assert parse_hotkey(f'ctrl+alt+{key}') == (3, code)


def test_default_hotkey():
    assert Settings.model_fields['desktop_hotkey'].default == 'ctrl+alt+numpad0'


def test_registration_failure_names_configured_hotkey(monkeypatch):
    user32 = Mock()
    user32.RegisterHotKey.return_value = 0
    kernel32 = Mock()
    kernel32.GetCurrentThreadId.return_value = 123
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=user32, kernel32=kernel32), raising=False)
    hotkey = GlobalHotkey('ctrl+alt+numpad0', Mock())
    hotkey._run()
    assert hotkey._ready.is_set()
    assert hotkey._error == '全局快捷键 ctrl+alt+numpad0 注册失败，可能已被其他程序占用。'
    user32.RegisterHotKey.assert_called_once_with(None, 1, 3, 0x60)
    hotkey.callback.assert_not_called()


def test_conflict_keeps_desktop_running(caplog):
    from zhaoxi.desktop.app import DesktopHost
    host = DesktopHost.__new__(DesktopHost)
    for name in ('instance', 'window', 'tray', 'hotkey', '_initialize_core', '_start_server', 'stop'):
        setattr(host, name, Mock())
    host.hotkey.start.side_effect = RuntimeError('全局快捷键 ctrl+alt+numpad0 注册失败，可能已被其他程序占用。')
    assert host.run(background=True)
    host.tray.start.assert_called_once()
    host.window.run.assert_called_once()
    assert 'ctrl+alt+numpad0' in caplog.text


def test_hotkey_toggle_hides_then_restores_window():
    from zhaoxi.desktop.window import DesktopWindow
    window = DesktopWindow('http://localhost', width=1000, height=700)
    window._window = Mock()
    window._ready.set()
    window.show_companion()
    window.toggle()
    window._window.hide.assert_called_once()
    assert not window._visible
    window.toggle()
    assert window._visible
    assert window._window.restore.call_count == 0


def test_hotkey_restores_minimized_window_instead_of_hiding():
    from zhaoxi.desktop.window import DesktopWindow
    window = DesktopWindow('http://localhost', width=1000, height=700)
    window._window = Mock()
    window._ready.set()
    window.show()
    window._on_minimized()
    window.toggle()
    window._window.hide.assert_not_called()
    assert not window._minimized
    assert window._window.restore.call_count == 1
    window.toggle()
    window._window.hide.assert_called_once()
