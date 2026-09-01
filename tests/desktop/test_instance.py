import threading

import pytest

from zhaoxi.desktop.hotkey import parse_hotkey
from zhaoxi.desktop.instance import InstanceCoordinator


def test_single_instance_activates_existing_owner(tmp_path):
    activated = threading.Event()
    state_path = tmp_path / "desktop-instance.json"
    primary = InstanceCoordinator(state_path, 0)
    assert primary.acquire(activated.set)

    secondary = InstanceCoordinator(state_path, primary.port)
    assert not secondary.acquire(lambda: None)
    assert activated.wait(timeout=2)

    primary.close()
    assert not state_path.exists()


def test_stale_instance_state_has_readable_error(tmp_path):
    state_path = tmp_path / "desktop-instance.json"
    state_path.write_text('{"port": 9, "token": "stale"}', encoding="utf-8")
    instance = InstanceCoordinator(state_path, 9)
    with pytest.raises(RuntimeError, match="无法激活"):
        instance.activate_existing()


def test_hotkey_parser_accepts_bounded_shortcut():
    modifiers, key = parse_hotkey("ctrl+alt+space")
    assert modifiers == 0x0002 | 0x0001
    assert key == 0x20


@pytest.mark.parametrize("value", ["space", "ctrl+mouse1", "ctrl+banana+space"])
def test_hotkey_parser_rejects_unsupported_shortcut(value):
    with pytest.raises(ValueError):
        parse_hotkey(value)
