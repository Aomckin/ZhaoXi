from unittest.mock import Mock
import json

from zhaoxi.desktop.window import DesktopWindow, WindowMode


def make_window(tmp_path):
    window = DesktopWindow('http://local',width=1080,height=760,geometry_path=tmp_path/'geometry.json')
    window._window = Mock()
    window._native = Mock()
    window._native.snapshot.return_value = dict(x=120,y=90,width=1080,height=760,maximized=True)
    window._loaded.set()
    return window


def test_twenty_roundtrips_keep_identity_and_geometry(tmp_path):
    window = make_window(tmp_path)
    identity = window._window
    main = dict(window._native.snapshot.return_value)
    companion = dict(x=700,y=100,width=410,height=510,maximized=False)
    for _ in range(20):
        window._native.snapshot.return_value = main
        window.switch_mode('companion')
        assert window.mode == WindowMode.COMPANION
        window._native.snapshot.return_value = companion
        window.switch_mode('main')
        window._native.apply.assert_called_with(window.geometries['main'],'main')
        assert window.geometries['main']['maximized'] is True
        assert window.geometries['companion']['width'] == 410
        assert window._window is identity
    identity.load_url.assert_not_called()
    identity.destroy.assert_not_called()
    restored = DesktopWindow('url',width=1080,height=760,geometry_path=tmp_path/'geometry.json')
    assert restored.geometries['main']['x'] == 120
    assert restored.geometries['companion']['width'] == 410


def test_topmost_is_idempotent_and_not_reapplied_by_events(tmp_path):
    window = make_window(tmp_path)
    window.switch_mode('companion')
    window.set_topmost(True)
    for _ in range(1000):
        window.set_topmost(True,remember=False)
        window._on_restored()
    window._native.topmost.assert_called_once_with(True)
    assert window.native_topmost_calls == 1
    window.switch_mode('main')
    assert window.native_topmost_calls == 2
    assert window.geometries['companion']['topmost'] is True
    window.switch_mode('companion')
    assert window.native_topmost_calls == 3
    window.set_topmost(False)
    assert window.native_topmost_calls == 4


def test_double_click_expands_companion_never_maximizes(tmp_path):
    window = make_window(tmp_path)
    window.switch_mode('companion')
    window.title_double_click()
    assert window.mode == WindowMode.MAIN
    window._native.maximize.assert_not_called()
    window.title_double_click()
    window._native.maximize.assert_called_once()


def test_bad_geometry_uses_defaults(tmp_path):
    file = tmp_path/'geometry.json'
    file.write_text('{"main":{"x":0,"y":0,"width":-1,"height":100}}')
    window = DesktopWindow('url',width=1080,height=760,geometry_path=file)
    assert window.geometries['main']['width'] == 1080


def test_notification_focused_suppression_and_route(tmp_path):
    from zhaoxi.desktop.notifications import NativeNotifier
    from zhaoxi.desktop.app import DesktopHost
    window = make_window(tmp_path)
    window._visible = True
    window._native.focused.return_value = True
    notifier = NativeNotifier(window,Mock(),system_mode=True)
    notifier.show('notice','text','id')
    assert notifier._fallback is None
    host = DesktopHost.__new__(DesktopHost)
    host.window = window
    host.notifier = Mock()
    host._notification_modes = {}
    host._notify_delivery('朝汐提醒','message','conversation')
    host._open_delivery('conversation')
    assert window.mode == WindowMode.COMPANION
    host._notify_delivery('朝汐 · 重要提醒','message','important')
    host._open_delivery('important')
    assert window.mode == WindowMode.MAIN


def test_native_hit_zones_across_dpi_and_negative_monitor():
    from zhaoxi.desktop.native import resize_hit_test
    for dpi in (96,120,144,168,192):
        border = round(6*dpi/96)
        left,top,right,bottom = -1920,-200,-1520,300
        cases = [(left,top,13),(right-1,top,14),(left,bottom-1,16),(right-1,bottom-1,17),
                 (left,0,10),(right-1,0,11),(-1700,top,12),(-1700,bottom-1,15),(-1700,0,0)]
        for x,y,expected in cases:
            assert resize_hit_test(x,y,left,top,right,bottom,border) == expected
        assert resize_hit_test(right,top,left,top,right,bottom,border) == 0
