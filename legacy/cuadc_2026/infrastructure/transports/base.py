"""Byte-only contract; no vehicle or protocol types cross this boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class TransportHealth:
    is_open: bool
    last_error: str | None = None


@runtime_checkable
class ByteTransport(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...
    def read(self, max_bytes: int) -> bytes: ...
    def write(self, data: bytes) -> int: ...

    @property
    def is_open(self) -> bool: ...

    def health(self) -> TransportHealth: ...
