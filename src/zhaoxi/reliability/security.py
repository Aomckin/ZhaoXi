"""Deterministic validation for model-produced Tool arguments."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from urllib.parse import urlparse


class UnsafeToolArgument(ValueError):
    pass


def validate_tool_arguments(
    arguments: dict,
    *,
    max_chars: int = 50_000,
    max_depth: int = 12,
    allowed_path_roots: tuple[Path, ...] = (),
) -> None:
    serialized = json.dumps(arguments, ensure_ascii=False, default=str)
    if len(serialized) > max_chars:
        raise UnsafeToolArgument("工具参数总大小超过安全上限。")
    _walk(arguments, depth=0, max_depth=max_depth, allowed_path_roots=allowed_path_roots)


def _walk(value, *, depth: int, max_depth: int, allowed_path_roots: tuple[Path, ...], key=""):
    if depth > max_depth:
        raise UnsafeToolArgument("工具参数嵌套层级超过安全上限。")
    if isinstance(value, dict):
        if len(value) > 200:
            raise UnsafeToolArgument("工具参数字段过多。")
        for child_key, child in value.items():
            _walk(
                child,
                depth=depth + 1,
                max_depth=max_depth,
                allowed_path_roots=allowed_path_roots,
                key=str(child_key).lower(),
            )
    elif isinstance(value, list):
        if len(value) > 1000:
            raise UnsafeToolArgument("工具参数集合过大。")
        for child in value:
            _walk(
                child,
                depth=depth + 1,
                max_depth=max_depth,
                allowed_path_roots=allowed_path_roots,
                key=key,
            )
    elif isinstance(value, str):
        if "url" in key or key in {"uri", "endpoint"}:
            _validate_url(value)
        if key in {"path", "file_path", "directory", "root"} and allowed_path_roots:
            _validate_path(value, allowed_path_roots)


def _validate_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeToolArgument("URL 必须使用 HTTP(S) 且包含主机名。")
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"}:
        raise UnsafeToolArgument("URL 不允许访问本机地址。")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise UnsafeToolArgument("URL 不允许访问私有、回环或链路本地地址。")


def _validate_path(value: str, roots: tuple[Path, ...]) -> None:
    target = Path(value).resolve()
    resolved_roots = tuple(root.resolve() for root in roots)
    if not any(target == root or root in target.parents for root in resolved_roots):
        raise UnsafeToolArgument("路径超出允许范围。")
