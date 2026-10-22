"""MAVLink 2 framing for explicitly translated ArduPilot instructions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from pymavlink.dialects.v20 import ardupilotmega as mavlink


@dataclass(frozen=True, slots=True)
class CommandLong:
    command: int
    params: tuple[float, float, float, float, float, float, float]


@dataclass(frozen=True, slots=True)
class LocalSetpoint:
    frame: int
    type_mask: int
    time_boot_ms: int = 0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    yaw: float = 0.0
    yaw_rate: float = 0.0


Instruction: TypeAlias = CommandLong | LocalSetpoint


class MavlinkCodec:
    """Message construction/parsing only; never owns a socket or writer."""

    def __init__(self, *, source_system: int, source_component: int,
                 target_system: int, target_component: int) -> None:
        for value in (source_system, source_component, target_system, target_component):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 255:
                raise ValueError("MAVLink system/component IDs must be 1..255")
        self.source_system = source_system
        self.source_component = source_component
        self.target_system = target_system
        self.target_component = target_component
        self._sender = mavlink.MAVLink(None, srcSystem=source_system, srcComponent=source_component)
        self._receiver = mavlink.MAVLink(None)

    def encode(self, instruction: Instruction) -> bytes:
        if isinstance(instruction, CommandLong):
            message = self._sender.command_long_encode(
                self.target_system, self.target_component, instruction.command, 0,
                *instruction.params,
            )
        elif isinstance(instruction, LocalSetpoint):
            message = self._sender.set_position_target_local_ned_encode(
                instruction.time_boot_ms, self.target_system, self.target_component, instruction.frame,
                instruction.type_mask, instruction.x, instruction.y, instruction.z,
                instruction.vx, instruction.vy, instruction.vz, 0, 0, 0,
                instruction.yaw, instruction.yaw_rate,
            )
        else:
            raise TypeError("unsupported MAVLink instruction")
        return message.pack(self._sender)

    def feed(self, data: bytes) -> tuple[object, ...]:
        if not isinstance(data, bytes):
            raise TypeError("MAVLink input must be bytes")
        messages = []
        for value in data:
            try:
                message = self._receiver.parse_char(bytes((value,)))
            except mavlink.MAVError:
                continue
            if message is not None and message.get_type() != "BAD_DATA":
                messages.append(message)
        return tuple(messages)
