"""Transport selection independent of source identity and vehicle protocol."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TransportKind(str, Enum):
    SERIAL = "serial"
    UDP = "udp"
    TCP = "tcp"


@dataclass(frozen=True, slots=True)
class TransportSpec:
    kind: TransportKind
    device: str | None = None
    baudrate: int | None = None
    host: str | None = None
    port: int | None = None
    udp_mode: str | None = None
    timeout_s: float = 0.2

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TransportKind):
            raise TypeError("kind must be a TransportKind")
        if self.timeout_s <= 0:
            raise ValueError("transport timeout must be positive")
        if self.kind is TransportKind.SERIAL:
            if not self.device or not self.baudrate or self.baudrate <= 0:
                raise ValueError("serial transport requires device and baudrate")
        else:
            if not self.host or self.port is None or not 1 <= self.port <= 65535:
                raise ValueError("network transport requires host and port")
        if self.kind is TransportKind.UDP and self.udp_mode not in {"udpin", "udpout"}:
            raise ValueError("UDP mode must be udpin or udpout")

    @property
    def endpoint(self) -> str:
        if self.kind is TransportKind.SERIAL:
            assert self.device is not None
            return self.device
        assert self.host is not None and self.port is not None
        prefix = self.udp_mode if self.kind is TransportKind.UDP else "tcp"
        return f"{prefix}:{self.host}:{self.port}"
