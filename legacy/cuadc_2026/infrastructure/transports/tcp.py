"""Blocking TCP byte stream for a vehicle link."""

from __future__ import annotations

import socket

from .base import TransportHealth
from .spec import TransportKind, TransportSpec


class TcpTransport:
    def __init__(self, spec: TransportSpec) -> None:
        if spec.kind is not TransportKind.TCP:
            raise ValueError("TCP transport requires TCP spec")
        self.spec = spec
        self._socket: socket.socket | None = None
        self._last_error: str | None = None

    def open(self) -> None:
        if self.is_open:
            return
        try:
            sock = socket.create_connection((self.spec.host, self.spec.port), self.spec.timeout_s)
            sock.settimeout(self.spec.timeout_s)
            self._socket = sock
            self._last_error = None
        except OSError as exc:
            self._last_error = type(exc).__name__
            raise

    def close(self) -> None:
        sock, self._socket = self._socket, None
        if sock is not None:
            sock.close()

    def read(self, max_bytes: int) -> bytes:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if self._socket is None:
            raise RuntimeError("transport_closed")
        return self._socket.recv(max_bytes)

    def write(self, data: bytes) -> int:
        if self._socket is None:
            raise RuntimeError("transport_closed")
        self._socket.sendall(data)
        return len(data)

    @property
    def is_open(self) -> bool:
        return self._socket is not None

    def health(self) -> TransportHealth:
        return TransportHealth(self.is_open, self._last_error)
