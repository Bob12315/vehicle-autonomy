"""Datagram byte transport with explicit inbound or outbound endpoint mode."""

from __future__ import annotations

import socket

from .base import TransportHealth
from .spec import TransportKind, TransportSpec


class UdpTransport:
    def __init__(self, spec: TransportSpec) -> None:
        if spec.kind is not TransportKind.UDP:
            raise ValueError("UDP transport requires UDP spec")
        self.spec = spec
        self._socket: socket.socket | None = None
        self._peer: tuple[str, int] | None = None
        self._last_error: str | None = None

    def open(self) -> None:
        if self.is_open:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(self.spec.timeout_s)
            assert self.spec.host is not None and self.spec.port is not None
            if self.spec.udp_mode == "udpin":
                sock.bind((self.spec.host, self.spec.port))
            else:
                self._peer = (self.spec.host, self.spec.port)
                sock.connect(self._peer)
            self._socket = sock
            self._last_error = None
        except OSError as exc:
            sock.close()
            self._last_error = type(exc).__name__
            raise

    def close(self) -> None:
        sock, self._socket = self._socket, None
        self._peer = None
        if sock is not None:
            sock.close()

    def read(self, max_bytes: int) -> bytes:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if self._socket is None:
            raise RuntimeError("transport_closed")
        if self.spec.udp_mode == "udpin":
            payload, self._peer = self._socket.recvfrom(max_bytes)
            return payload
        return self._socket.recv(max_bytes)

    def write(self, data: bytes) -> int:
        if self._socket is None:
            raise RuntimeError("transport_closed")
        if self.spec.udp_mode == "udpin":
            if self._peer is None:
                raise RuntimeError("udp_peer_unknown")
            return self._socket.sendto(data, self._peer)
        return self._socket.send(data)

    @property
    def is_open(self) -> bool:
        return self._socket is not None

    def health(self) -> TransportHealth:
        return TransportHealth(self.is_open, self._last_error)
