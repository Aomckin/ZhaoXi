"""Isolated native smoke; no Core, tray, hotkey or user data."""
import json
import time
from pathlib import Path
from zhaoxi.desktop.window import DesktopWindow
from zhaoxi.desktop.notifications import NativeNotifier

out = Path('build/v1.2.1/native-smoke.json')
fixture = Path('build/v1.2.1/native-fixture.html')
fixture.write_text('<html><body>朝汐隔离窗口验收<script>window.identityMarker = Math.random();</script></body></html>',encoding='utf-8')
window = DesktopWindow(str(fixture.resolve()),width=1080,height=760)
original = window._on_started

def checks():
    try:
        original()
        window.show()
        assert window._loaded.wait(20), "WebView not loaded"
        identity = window._window.native.Handle.ToInt64()
        marker = window._window.evaluate_js("window.identityMarker")
        import ctypes
        from ctypes import wintypes
        from zhaoxi.desktop.native import invoke
        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        def hit_tests():
            geo = window._native.snapshot()
            x,y,w,h = (geo[k] for k in ('x','y','width','height'))
            for dx,dy,expected in [(1,h//2,10),(w-1,h//2,11),(w//2,1,12),(w//2,h-1,15),(1,1,13),(w-1,1,14),(1,h-1,16),(w-1,h-1,17)]:
                lp = ((y+dy)&0xffff)<<16 | ((x+dx)&0xffff)
                actual = invoke(window._window,lambda _: user32.SendMessageW(identity,0x0084,0,lp))
                assert actual == expected, (actual,expected)
        hit_tests()
        for _ in range(20):
            window.switch_mode('companion')
            assert window._native.snapshot()['width'] == 390
            hit_tests()
            window.switch_mode('main')
            assert window._native.snapshot()['width'] == 1080
            assert window._window.native.Handle.ToInt64() == identity
        assert window._window.evaluate_js('window.identityMarker') == marker
        window.title_double_click()
        assert window._native.snapshot()['maximized']
        window.title_double_click()
        assert not window._native.snapshot()['maximized']
        window.switch_mode('companion')
        invoke(window._window,lambda _: user32.SendMessageW(identity,0x0112,0xf030,0))
        assert not window._native.snapshot()['maximized']
        window.set_topmost(True)
        for _ in range(100):
            window._on_restored()
        assert window.native_topmost_calls == 1
        soak = float(__import__('os').environ.get('ZHAOXI_TEST_SOAK_SECONDS', '60'))
        before_cpu = time.process_time()
        time.sleep(soak)
        idle_cpu_seconds = time.process_time() - before_cpu
        assert window.native_topmost_calls == 1
        window.set_topmost(False)
        window.title_double_click()
        assert window.mode == 'main'
        window.hide()
        notifier = NativeNotifier(window,lambda _: None)
        notifier.show('朝汐 · 开发验收','这是隔离测试通知，将立即关闭。','smoke')
        assert notifier._card is not None, 'Native notification fell back'
        notifier.stop()
        out.write_text(json.dumps({'ok':True,'roundtrips':20,'hwnd':identity,'topmost_calls':window.native_topmost_calls,'webview_identity_preserved':True,'native_hit_tests':168,'soak_seconds':soak,'idle_cpu_seconds':idle_cpu_seconds}),encoding='utf-8')
    except Exception:
        import traceback
        out.write_text(json.dumps({'ok':False,'error':traceback.format_exc()}),encoding='utf-8')
    finally:
        window.destroy()

window._on_started = checks
window.run(background=True)

if not json.loads(out.read_text(encoding='utf-8')).get('ok'):
    raise SystemExit(1)
