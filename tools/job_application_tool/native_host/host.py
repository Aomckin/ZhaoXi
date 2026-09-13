"""Chrome/Edge Native Messaging stdio host and local request broker."""

from __future__ import annotations

import json
import os
import queue
import struct
import sys
import threading
from multiprocessing.connection import Listener
from pathlib import Path
from typing import Any, BinaryIO

from pydantic import ValidationError

from tools.job_application_tool.native_host.protocol import (
    DEFAULT_UNIX_SOCKET,
    DEFAULT_WINDOWS_PIPE,
    MAX_NATIVE_MESSAGE_BYTES,
    HOST_VERSION,
    RequestEnvelope,
    ResponseEnvelope,
    error_response,
)
from tools.job_application_tool.native_host.session import PendingRequests


class NativeHostBroker:
    def __init__(self, address: str | None = None) -> None:
        self.address = address or (DEFAULT_WINDOWS_PIPE if os.name == "nt" else DEFAULT_UNIX_SOCKET)
        self.family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
        self.pending = PendingRequests()
        self.stdout_lock = threading.Lock()
        self.stopped = threading.Event()

    @staticmethod
    def validate_request(message: object) -> tuple[bool, str]:
        try:
            RequestEnvelope.model_validate(message)
        except ValidationError as exc:
            error_type = exc.errors()[0].get("type", "invalid_message")
            return False, "protocol_mismatch" if "literal" in error_type else "invalid_message"
        return True, ""

    @staticmethod
    def read_framed(stream: BinaryIO) -> dict[str, Any] | None:
        header = stream.read(4)
        if not header:
            return None
        if len(header) != 4:
            raise ValueError("malformed native message header")
        length = struct.unpack("<I", header)[0]
        if length > MAX_NATIVE_MESSAGE_BYTES:
            raise ValueError("native message too large")
        body = stream.read(length)
        if len(body) != length:
            raise ValueError("truncated native message")
        parsed = json.loads(body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("native message must be an object")
        return parsed

    @staticmethod
    def encode_framed(message: dict[str, Any]) -> bytes:
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_NATIVE_MESSAGE_BYTES:
            raise ValueError("native message too large")
        return struct.pack("<I", len(encoded)) + encoded

    def write_native(self, message: dict[str, Any]) -> None:
        framed = self.encode_framed(message)
        with self.stdout_lock:
            sys.stdout.buffer.write(framed)
            sys.stdout.buffer.flush()

    def read_native_loop(self) -> None:
        while not self.stopped.is_set():
            try:
                response = self.read_framed(sys.stdin.buffer)
                if response is None:
                    self.stopped.set()
                    return
                validated = ResponseEnvelope.model_validate(response)
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError, ValidationError):
                continue
            self.pending.deliver(validated.request_id, validated.model_dump())

    def handle_connection(self, connection) -> None:
        request_id = "invalid"
        session_id = "current"
        try:
            raw = connection.recv()
            try:
                request = RequestEnvelope.model_validate(raw)
            except ValidationError:
                connection.send(error_response(request_id, session_id, "protocol_mismatch", "Native broker rejected the request."))
                return
            request_id, session_id = request.request_id, request.session_id
            waiter = self.pending.create(request_id)
            if waiter is None:
                connection.send(error_response(request_id, session_id, "protocol_mismatch", "Duplicate request id."))
                return
            try:
                self.write_native(request.model_dump())
                response = waiter.get(timeout=request.deadline_ms / 1000)
                if request.type == "bridge_status" and response.get("ok") and isinstance(response.get("result"), dict):
                    response["result"] = {**response["result"], "native_host_version": HOST_VERSION}
                connection.send(response)
            except queue.Empty:
                connection.send(error_response(request_id, session_id, "timeout", "Browser extension did not respond."))
            finally:
                self.pending.remove(request_id)
        except (EOFError, OSError):
            return
        finally:
            connection.close()

    def run(self) -> None:
        socket_path = Path(self.address) if self.family == "AF_UNIX" else None
        if socket_path and socket_path.exists():
            socket_path.unlink()
        threading.Thread(target=self.read_native_loop, daemon=True).start()
        listener = Listener(self.address, family=self.family)
        try:
            while not self.stopped.is_set():
                connection = listener.accept()
                threading.Thread(target=self.handle_connection, args=(connection,), daemon=True).start()
        finally:
            listener.close()
            if socket_path and socket_path.exists():
                socket_path.unlink()


def main() -> None:
    NativeHostBroker().run()


if __name__ == "__main__":
    main()
