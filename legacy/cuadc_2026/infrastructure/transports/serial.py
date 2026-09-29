"""Blocking serial byte stream; USB and radio tty devices use the same type."""

from __future__ import annotations

from .base import TransportHealth
from .spec import TransportKind, TransportSpec


class SerialTransport:
    def __init__(self, spec: TransportSpec) -> None:
        if spec.kind is not TransportKind.SERIAL:
            raise ValueError("serial transport requires serial spec")
        self.spec = spec
        self._serial = None
        self._last_error: str | None = None

    def open(self) -> None:
        if self.is_open:
            return
        try:
            import serial

            self._serial = serial.Serial(
                self.spec.device, baudrate=self.spec.baudrate,
                timeout=self.spec.timeout_s, write_timeout=self.spec.timeout_s,
            )
            self._last_error = None
        except Exception as exc:
            self._last_error = type(exc).__name__
            self._serial = None
            raise

    def close(self) -> None:
        handle, self._serial = self._serial, None
        if handle is not None:
            handle.close()

    def read(self, max_bytes: int) -> bytes:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if not self.is_open:
            raise RuntimeError("transport_closed")
        return bytes(self._serial.read(max_bytes))

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise RuntimeError("transport_closed")
        return int(self._serial.write(data))

    @property
    def is_open(self) -> bool:
        return self._serial is not None and bool(self._serial.is_open)

    def health(self) -> TransportHealth:
        return TransportHealth(self.is_open, self._last_error)
