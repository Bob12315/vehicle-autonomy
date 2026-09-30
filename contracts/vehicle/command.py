"""Commands prepared for submission after later Execution approval checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import TypeAlias

from contracts.core.geometry import FrameId, Pose3, Twist3
from contracts.core.primitives import (
    CommandId, IdempotencyKey, LeaseId, LinkSessionId, RunId, SchemaVersion,
)
from contracts.core.time import TimePoint


@dataclass(frozen=True, slots=True)
class ArmCommand:
    pass


@dataclass(frozen=True, slots=True)
class DisarmCommand:
    pass


@dataclass(frozen=True, slots=True)
class TakeoffCommand:
    height_m: float

    def __post_init__(self) -> None:
        if isinstance(self.height_m, bool) or not isinstance(self.height_m, (int, float)) or not math.isfinite(self.height_m) or self.height_m <= 0:
            raise ValueError("height_m must be a finite positive SI distance")


@dataclass(frozen=True, slots=True)
class LandCommand:
    pass


@dataclass(frozen=True, slots=True)
class ModeCommand:
    native_mode: str

    def __post_init__(self) -> None:
        if not isinstance(self.native_mode, str) or not self.native_mode.strip():
            raise ValueError("native_mode must be non-empty")


@dataclass(frozen=True, slots=True)
class PoseTargetCommand:
    frame_id: FrameId
    target_pose: Pose3
    stream_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.frame_id, FrameId):
            object.__setattr__(self, "frame_id", FrameId(self.frame_id))
        if not isinstance(self.target_pose, Pose3):
            raise TypeError("target_pose must be Pose3")
        if not isinstance(self.stream_id, str) or not self.stream_id.strip():
            raise ValueError("stream_id must be non-empty")


@dataclass(frozen=True, slots=True)
class TwistTargetCommand:
    frame_id: FrameId
    target_twist: Twist3
    stream_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.frame_id, FrameId):
            object.__setattr__(self, "frame_id", FrameId(self.frame_id))
        if not isinstance(self.target_twist, Twist3):
            raise TypeError("target_twist must be Twist3")
        if not isinstance(self.stream_id, str) or not self.stream_id.strip():
            raise ValueError("stream_id must be non-empty")


@dataclass(frozen=True, slots=True)
class StopMotionCommand:
    stream_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.stream_id, str) or not self.stream_id.strip():
            raise ValueError("stream_id must be non-empty")


VehicleCommand: TypeAlias = (
    ArmCommand | DisarmCommand | TakeoffCommand | LandCommand | ModeCommand
    | PoseTargetCommand | TwistTargetCommand | StopMotionCommand
)


@dataclass(frozen=True, slots=True)
class VehicleCommandEnvelope:
    schema_version: SchemaVersion
    command_id: CommandId
    run_id: RunId
    lease_id: LeaseId
    authorization_generation: int
    send_generation: int
    expected_link_session_id: LinkSessionId
    created_at: TimePoint
    deadline: TimePoint
    priority: int
    idempotency_key: IdempotencyKey
    command: VehicleCommand

    def __post_init__(self) -> None:
        for name, kind in (("command_id", CommandId), ("run_id", RunId), ("lease_id", LeaseId), ("expected_link_session_id", LinkSessionId), ("idempotency_key", IdempotencyKey)):
            value = getattr(self, name)
            if not isinstance(value, kind):
                object.__setattr__(self, name, kind(value))
        if not isinstance(self.schema_version, SchemaVersion):
            raise TypeError("schema_version must be SchemaVersion")
        for name in ("authorization_generation", "send_generation", "priority"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.created_at, TimePoint) or not isinstance(self.deadline, TimePoint):
            raise TypeError("command times must be TimePoint values")
        if self.deadline.elapsed_ns_since(self.created_at) <= 0:
            raise ValueError("command deadline must follow creation")
        if not isinstance(self.command, (ArmCommand, DisarmCommand, TakeoffCommand, LandCommand, ModeCommand, PoseTargetCommand, TwistTargetCommand, StopMotionCommand)):
            raise TypeError("command must be a typed VehicleCommand")


class CommandPhase(str, Enum):
    ACCEPTED = "ACCEPTED"
    TRANSMITTED = "TRANSMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class CommandStatus:
    command_id: CommandId
    phase: CommandPhase
    observed_at: TimePoint

    def __post_init__(self) -> None:
        if not isinstance(self.command_id, CommandId):
            object.__setattr__(self, "command_id", CommandId(self.command_id))
        if not isinstance(self.phase, CommandPhase) or not isinstance(self.observed_at, TimePoint):
            raise TypeError("status requires CommandPhase and TimePoint")


@dataclass(frozen=True, slots=True)
class CancelCommandRequest:
    command_id: CommandId
    requested_at: TimePoint

    def __post_init__(self) -> None:
        if not isinstance(self.command_id, CommandId):
            object.__setattr__(self, "command_id", CommandId(self.command_id))
        if not isinstance(self.requested_at, TimePoint):
            raise TypeError("requested_at must be TimePoint")


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    command_id: CommandId
    phase: CommandPhase

    def __post_init__(self) -> None:
        if not isinstance(self.command_id, CommandId):
            object.__setattr__(self, "command_id", CommandId(self.command_id))
        if not isinstance(self.phase, CommandPhase):
            raise TypeError("phase must be CommandPhase")
