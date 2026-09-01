"""Single-instance coordination with a loopback activation channel."""

from __future__ import annotations

import json
import secrets
import socket
import threading
from pathlib import Path
from typing import Callable


class InstanceCoordinator:
    """Own a loopback port or authenticate and activate its current owner."""

    def __init__(self, state_path: str | Path, port: int) -> None:
        self.state_path = Path(state_path)
        self.port = port
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._token: str | None = None

    def acquire(self, on_activate: Callable[[], None]) -> bool:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(("127.0.0.1", self.port))
        except OSError:
            server.close()
            self.activate_existing()
            return False
        server.listen(4)
        server.settimeout(0.25)
        self._socket = server
        self._token = secrets.token_urlsafe(32)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps({"port": server.getsockname()[1], "token": self._token}),
            encoding="utf-8",
        )
        self.port = server.getsockname()[1]
        self._thread = threading.Thread(
            target=self._serve,
            args=(on_activate,),
            name="zhaoxi-instance-activation",
            daemon=True,
        )
        self._thread.start()
        return True

    def activate_existing(self) -> None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            payload = json.dumps({"token": state["token"], "action": "show"}).encode("utf-8")
            with socket.create_connection(("127.0.0.1", int(state["port"])), timeout=1) as client:
                client.sendall(payload)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError("朝汐已在运行，但无法激活现有窗口。") from exc

    def _serve(self, on_activate: Callable[[], None]) -> None:
        assert self._socket is not None
        while not self._stop.is_set():
            try:
                client, _ = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with client:
                try:
                    raw = client.recv(4096)
                    message = json.loads(raw.decode("utf-8"))
                    if secrets.compare_digest(str(message.get("token", "")), self._token or ""):
                        on_activate()
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue

    def close(self) -> None:
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None
        try:
            self.state_path.unlink(missing_ok=True)
        except OSError:
            pass

    def __enter__(self) -> "InstanceCoordinator":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
