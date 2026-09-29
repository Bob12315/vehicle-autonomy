"""Decode COMMAND_ACK fields; broker correlation remains in AckRouter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandAckObservation:
    mav_command: int
    source_system: int
    source_component: int
    result: int
    progress: int | None
    target_system: int
    target_component: int


def decode_command_ack(message: object) -> CommandAckObservation:
    progress = getattr(message, "progress", None)
    return CommandAckObservation(
        mav_command=int(getattr(message, "command")),
        source_system=int(message.get_srcSystem()),
        source_component=int(message.get_srcComponent()),
        result=int(getattr(message, "result")),
        progress=None if progress is None else int(progress),
        target_system=int(getattr(message, "target_system", 0) or 0),
        target_component=int(getattr(message, "target_component", 0) or 0),
    )
