"""Chrome Native Messaging host and same-user IPC broker.

Chrome launches this process and owns stdin/stdout. A local AF_PIPE/AF_UNIX
listener accepts bounded requests from the Zhaoxi Tool Package and relays them
to the extension. Only structured protocol messages are accepted.
"""

from __future__ import annotations

import json
import os
import queue
import struct
import sys
import threading
from multiprocessing.connection import Listener
from pathlib import Path
from typing import Any

from tools.job_application_tool.client import (
    DEFAULT_UNIX_SOCKET,
    DEFAULT_WINDOWS_PIPE,
    PROTOCOL,
    PROTOCOL_VERSION,
)


MAX_NATIVE_MESSAGE_BYTES = 1024 * 1024
ALLOWED_TYPES = {
    "inspect_page",
    "build_plan",
    "apply_safe_fields",
    "get_review",
    "get_profile",
    "update_profile",
}


class NativeHostBroker:
    def __init__(self, address: str | None = None) -> None:
        self.address = address or (DEFAULT_WINDOWS_PIPE if os.name == "nt" else DEFAULT_UNIX_SOCKET)
        self.family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
        self.pending: dict[str, queue.Queue[dict[str, Any]]] = {}
        self.lock = threading.Lock()
        self.stdout_lock = threading.Lock()
        self.stopped = threading.Event()

    @staticmethod
    def _error(request_id: str, code: str, message: str) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL,
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "ok": False,
            "error": code,
            "message": message,
        }

    @staticmethod
    def validate_request(message: object) -> tuple[bool, str]:
        if not isinstance(message, dict):
            return False, "invalid_message"
        allowed_keys = {"protocol", "version", "request_id", "type", "payload", "deadline_ms"}
        if set(message) - allowed_keys:
            return False, "unknown_message_fields"
        if message.get("protocol") != PROTOCOL or message.get("version") != PROTOCOL_VERSION:
            return False, "protocol_mismatch"
        if not isinstance(message.get("request_id"), str) or len(message["request_id"]) > 160:
            return False, "invalid_request_id"
        if message.get("type") not in ALLOWED_TYPES:
            return False, "unsupported_message_type"
        if not isinstance(message.get("payload"), dict):
            return False, "invalid_payload"
        return True, ""

    def write_native(self, message: dict[str, Any]) -> None:
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_NATIVE_MESSAGE_BYTES:
            raise ValueError("native message too large")
        with self.stdout_lock:
            sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
            sys.stdout.buffer.write(encoded)
            sys.stdout.buffer.flush()

    def read_native_loop(self) -> None:
        while not self.stopped.is_set():
            header = sys.stdin.buffer.read(4)
            if len(header) != 4:
                self.stopped.set()
                return
            length = struct.unpack("<I", header)[0]
            if length > MAX_NATIVE_MESSAGE_BYTES:
                self.stopped.set()
                return
            body = sys.stdin.buffer.read(length)
            if len(body) != length:
                self.stopped.set()
                return
            try:
                response = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            request_id = response.get("request_id") if isinstance(response, dict) else None
            with self.lock:
                waiter = self.pending.get(request_id)
            if waiter is not None:
                waiter.put(response)

    def handle_connection(self, connection) -> None:
        try:
            request = connection.recv()
            valid, code = self.validate_request(request)
            request_id = request.get("request_id", "invalid") if isinstance(request, dict) else "invalid"
            if not valid:
                connection.send(self._error(request_id, code, "Native broker rejected the request."))
                return
            waiter: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            with self.lock:
                if request_id in self.pending:
                    connection.send(self._error(request_id, "duplicate_request", "Duplicate request id."))
                    return
                self.pending[request_id] = waiter
            try:
                self.write_native(request)
                timeout = max(1.0, min(float(request.get("deadline_ms", 15000)) / 1000, 120.0))
                response = waiter.get(timeout=timeout)
                connection.send(response)
            except queue.Empty:
                connection.send(self._error(request_id, "browser_timeout", "Browser extension did not respond."))
            finally:
                with self.lock:
                    self.pending.pop(request_id, None)
        except (EOFError, OSError):
            return
        finally:
            connection.close()

    def run(self) -> None:
        if self.family == "AF_UNIX":
            socket_path = Path(self.address)
            if socket_path.exists():
                socket_path.unlink()
        reader = threading.Thread(target=self.read_native_loop, daemon=True)
        reader.start()
        listener = Listener(self.address, family=self.family)
        try:
            while not self.stopped.is_set():
                try:
                    connection = listener.accept()
                except (OSError, EOFError):
                    break
                threading.Thread(target=self.handle_connection, args=(connection,), daemon=True).start()
        finally:
            listener.close()
            if self.family == "AF_UNIX":
                socket_path = Path(self.address)
                if socket_path.exists():
                    socket_path.unlink()


def main() -> None:
    NativeHostBroker().run()


if __name__ == "__main__":
    main()
