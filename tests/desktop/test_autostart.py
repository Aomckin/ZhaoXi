import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zhaoxi.desktop import autostart
from zhaoxi.desktop.app import DesktopHost
from zhaoxi.desktop.window import DesktopWindow


def test_launch_config_uses_venv_pythonw_and_absolute_project():
    config = autostart.launch_config()
    assert config['executable'].endswith('pythonw.exe')
    assert '--desktop --background' in config['arguments']
    assert config['directory'] in config['arguments']


def test_install_requires_venv(monkeypatch):
    monkeypatch.setattr(sys, 'prefix', sys.base_prefix)
    with pytest.raises(RuntimeError, match='虚拟环境'):
        autostart.launch_config()


@pytest.mark.parametrize('action', ['install', 'status', 'remove'])
def test_management_passes_data_without_shell_interpolation(monkeypatch, action):
    runner = Mock(return_value=SimpleNamespace(returncode=0, stdout='{"installed":true}', stderr=''))
    monkeypatch.setattr(autostart.subprocess, 'run', runner)
    monkeypatch.setattr(autostart, 'launch_config', lambda: {'directory': "C:/中文 & ' spaces"})
    assert autostart.manage_autostart(action)['installed']
    args, kwargs = runner.call_args
    assert '-EncodedCommand' in args[0]
    assert kwargs['creationflags'] == autostart.subprocess.CREATE_NO_WINDOW
    assert json.loads(kwargs['input'])['action'] == action
    assert ('directory' in json.loads(kwargs['input'])) == (action == 'install')


def test_scheduler_failure_is_not_reported_as_uninstalled(monkeypatch):
    monkeypatch.setattr(autostart.subprocess, 'run', Mock(return_value=SimpleNamespace(
        returncode=1, stderr='Access denied', stdout='')))
    with pytest.raises(RuntimeError, match='Access denied'):
        autostart.manage_autostart('status')


@pytest.mark.parametrize('background', [False, True])
def test_window_initial_visibility_and_early_activation(monkeypatch, background):
    class Event:
        def __iadd__(self, callback):
            return self
    native = Mock(events=SimpleNamespace(loaded=Event(), closing=Event(), closed=Event(), minimized=Event(), restored=Event(), maximized=Event()))
    view = Mock()
    view.create_window.return_value = native
    view.start.side_effect = lambda callback: callback()
    monkeypatch.setitem(sys.modules, 'webview', view)
    window = DesktopWindow('http://localhost', width=1000, height=700)
    window.show()  # Activation arriving while the Core/server is still starting.
    window.run(background=background)
    assert view.create_window.call_args.kwargs['hidden'] is background
    native.show.assert_called_once()
    assert window._on_closing() is False
    native.hide.assert_called_once()
    window.destroy()
    assert window._on_closing() is True


def host_stub():
    host = DesktopHost.__new__(DesktopHost)
    for name in ('instance', 'window', 'tray', 'hotkey', '_initialize_core', '_start_server', 'stop'):
        setattr(host, name, Mock())
    return host


def test_secondary_does_not_initialize_core_or_services():
    host = host_stub()
    host.instance.acquire.return_value = False
    assert host.run() is False
    host._initialize_core.assert_not_called()
    host._start_server.assert_not_called()
    host.tray.start.assert_not_called()
    host.stop.assert_not_called()  # Must not remove the owner's instance state.


@pytest.mark.parametrize('background', [False, True])
def test_primary_starts_services_and_cleans_up(background):
    host = host_stub()
    assert host.run(background=background)
    host._initialize_core.assert_called_once()
    host._start_server.assert_called_once()
    host.tray.start.assert_called_once()
    assert host.window.run.call_args.kwargs['background'] is background
    host.stop.assert_called_once()


def test_startup_failure_releases_instance():
    host = host_stub()
    host._initialize_core.side_effect = RuntimeError('failed')
    with pytest.raises(RuntimeError):
        host.run(background=True)
    host.stop.assert_called_once()


@pytest.mark.parametrize('flag,action', [('--install-autostart', 'install'), ('--remove-autostart', 'remove'), ('--autostart-status', 'status')])
def test_cli_autostart_dispatch(monkeypatch, flag, action):
    from zhaoxi import cli
    manage = Mock(return_value={'installed': False})
    monkeypatch.setattr(autostart, 'manage_autostart', manage)
    monkeypatch.setattr(sys, 'argv', ['main.py', flag])
    cli.main()
    manage.assert_called_once_with(action)


def test_background_requires_desktop(monkeypatch):
    from zhaoxi import cli
    monkeypatch.setattr(sys, 'argv', ['main.py', '--background'])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_public_desktop_entry_forwards_background(monkeypatch):
    import zhaoxi.desktop
    import zhaoxi.desktop.app
    run = Mock()
    monkeypatch.setattr(zhaoxi.desktop.app, 'run_desktop', run)
    zhaoxi.desktop.run_desktop(background=True)
    run.assert_called_once_with(None, background=True)
