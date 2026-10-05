"""Shared isolation for Core and independently collected Tool package tests."""

import os
from pathlib import Path
import sqlite3
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

import pytest

from zhaoxi.config.settings import Settings

ROOT = Path(__file__).resolve().parent
PROTECTED = (ROOT / ".zhaoxi", ROOT / "data", ROOT / "config")


def _protected(path):
    if not isinstance(path, (str, os.PathLike)):
        return False
    if str(path).startswith("file:"):
        path = url2pathname(unquote(urlsplit(str(path)).path))
    resolved = Path(path).resolve()
    return any(resolved.is_relative_to(root) for root in PROTECTED)


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    """Redirect default state, ignore local credentials, and reject production writes."""
    for key in tuple(os.environ):
        if key.startswith(("ZHAOXI_", "MCP_")):
            monkeypatch.delenv(key)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    from zhaoxi.tools import packages
    monkeypatch.setattr(packages, "dotenv_values", lambda *args, **kwargs: {})
    state = tmp_path / "runtime"
    for name, field in Settings.model_fields.items():
        default = field.default
        if isinstance(default, str) and default.startswith(".zhaoxi/"):
            monkeypatch.setenv("ZHAOXI_" + name.upper(), str(state / default[8:]))
    monkeypatch.setenv("ZHAOXI_ARCHIVE_DIRECTORY", str(state / "archive"))
    monkeypatch.setenv("ZHAOXI_TOOL_OVERRIDES_PATH", str(state / "tool_overrides.json"))
    monkeypatch.setenv("ZHAOXI_EMOJI_REGISTRY_PATH", str(state / "emoji/emoji_registry.json"))
    monkeypatch.setenv("ZHAOXI_DECISION_USER_PRINCIPLES_DIRECTORY", str(state / "user_principles"))

    original_connect, original_open = sqlite3.connect, Path.open

    def connect(database, *args, **kwargs):
        if _protected(database):
            raise AssertionError(f"Test attempted to open production SQLite state: {database}")
        return original_connect(database, *args, **kwargs)

    def open_file(path, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+") and _protected(path):
            raise AssertionError(f"Test attempted to write production state: {path}")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(Path, "open", open_file)
    return state
