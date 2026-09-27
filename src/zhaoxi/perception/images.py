"""Controlled QQ image resolution for provider vision input."""
import asyncio
import base64
import ipaddress
import mimetypes
import socket
from datetime import datetime, timedelta, UTC
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx


def _mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class ImageResolver:
    def __init__(self, directory: str | Path, max_bytes: int, ttl_hours: int,
                 trusted_host: str | None = None, trusted_port: int | None = None):
        self.directory = Path(directory) / "qq"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.ttl_hours = ttl_hours
        self.trusted_host = trusted_host
        self.trusted_port = trusted_port
        self.last_status = "never"

    def _allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            return False
        local_aliases = {"localhost", "127.0.0.1", "::1"}
        same_host = parsed.hostname == self.trusted_host or (
            parsed.hostname in local_aliases and self.trusted_host in local_aliases)
        if same_host and parsed.port == self.trusted_port:
            return True
        if parsed.scheme != "https":
            return False
        try:
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or
                                            (443 if parsed.scheme == "https" else 80))
            return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global
                                           for item in addresses)
        except (OSError, ValueError):
            return False

    async def resolve(self, attachment: dict) -> str | None:
        source = attachment.get("url") or attachment.get("file") or ""
        try:
            if source.startswith("base64://"):
                data = base64.b64decode(source[9:], validate=True)
            elif source.startswith("data:image/") and ";base64," in source:
                data = base64.b64decode(source.split(";base64,", 1)[1], validate=True)
            elif await asyncio.to_thread(self._allowed, source):
                async with httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=15) as client:
                    async with client.stream("GET", source) as response:
                        response.raise_for_status()
                        if response.is_redirect:
                            raise ValueError("image redirect refused")
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > self.max_bytes:
                                raise ValueError("image too large")
                            chunks.append(chunk)
                        data = b"".join(chunks)
            else:
                raise ValueError("image source refused")
            if len(data) > self.max_bytes or not data:
                raise ValueError("invalid image size")
            mime = _mime(data)
            if mime is None:
                raise ValueError("unsupported image mime")
            suffix = mimetypes.guess_extension(mime) or ".img"
            (self.directory / (uuid4().hex + suffix)).write_bytes(data)
            self.last_status = "ok"
            return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        except Exception as exc:
            self.last_status = type(exc).__name__
            return None

    def clear_expired(self) -> int:
        cutoff = (datetime.now(UTC) - timedelta(hours=self.ttl_hours)).timestamp()
        count = 0
        for path in self.directory.iterdir():
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                count += 1
        return count
