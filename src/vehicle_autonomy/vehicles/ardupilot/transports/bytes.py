"""Byte transport boundary; opening a connection is always explicit."""

from __future__ import annotations

import socket
from typing import Protocol

import serial


class ByteTransport(Protocol):
    def write(self, data: bytes) -> None: ...
    def read(self, max_bytes: int = 4096) -> bytes | None: ...
    def close(self) -> None: ...


class TcpByteTransport:
    """One connected TCP stream, with no MAVLink or command semantics."""

    def __init__(self, connection: socket.socket) -> None:
        self._connection = connection
        self._closed = False

    @classmethod
    def connect(cls, host: str, port: int, *, timeout_s: float = 1.0) -> "TcpByteTransport":
        if not isinstance(host, str) or not host.strip():
            raise ValueError("host is required")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("invalid TCP port")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            raise ValueError("timeout must be positive")
        connection = socket.create_connection((host, port), timeout=timeout_s)
        connection.settimeout(timeout_s)
        return cls(connection)

    def write(self, data: bytes) -> None:
        if self._closed:
            raise ConnectionError("transport is closed")
        if not isinstance(data, bytes) or not data:
            raise ValueError("non-empty bytes required")
        self._connection.sendall(data)

    def read(self, max_bytes: int = 4096) -> bytes | None:
        if self._closed:
            raise ConnectionError("transport is closed")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        try:
            data = self._connection.recv(max_bytes)
        except socket.timeout:
            return None
        if not data:
            raise ConnectionError("transport disconnected")
        return data

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._connection.close()


class SerialByteTransport:
    """Explicit USB/UART byte stream; no MAVLink or vehicle command methods."""

    def __init__(self, connection: serial.Serial) -> None:
        self._connection = connection
        self._closed = False

    @classmethod
    def connect(cls, path: str, *, baudrate: int = 115200,
                timeout_s: float = 0.2) -> "SerialByteTransport":
        if not isinstance(path, str) or not path.startswith("/dev/"):
            raise ValueError("absolute /dev serial path required")
        if isinstance(baudrate, bool) or not isinstance(baudrate, int) or baudrate <= 0:
            raise ValueError("baudrate must be positive")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            raise ValueError("timeout must be positive")
        try:
            connection = serial.Serial(
                path, baudrate=baudrate, timeout=timeout_s,
                write_timeout=timeout_s, exclusive=True,
            )
        except serial.SerialException as exc:
            raise ConnectionError(f"cannot open serial transport: {path}") from exc
        return cls(connection)

    def write(self, data: bytes) -> None:
        if self._closed:
            raise ConnectionError("transport is closed")
        if not isinstance(data, bytes) or not data:
            raise ValueError("non-empty bytes required")
        try:
            count = self._connection.write(data)
        except serial.SerialException as exc:
            raise ConnectionError("serial write outcome uncertain") from exc
        if count != len(data):
            raise ConnectionError("partial serial write outcome uncertain")

    def read(self, max_bytes: int = 4096) -> bytes | None:
        if self._closed:
            raise ConnectionError("transport is closed")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        try:
            data = self._connection.read(max_bytes)
        except serial.SerialException as exc:
            raise ConnectionError("serial read failed") from exc
        return data or None

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._connection.close()
