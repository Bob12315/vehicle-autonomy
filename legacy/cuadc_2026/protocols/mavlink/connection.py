"""Compatibility boundary: pymavlink currently owns framing and byte transport."""

from __future__ import annotations

from pymavlink import mavutil


def open_pymavlink_connection(url: str, baud: int | None = None):
    if url.startswith("/dev/"):
        if baud is None:
            return mavutil.mavlink_connection(url)
        return mavutil.mavlink_connection(url, baud=int(baud))
    return mavutil.mavlink_connection(url)
