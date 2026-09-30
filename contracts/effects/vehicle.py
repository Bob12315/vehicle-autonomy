"""Typed vehicle effect requests, before authorization or safety evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import ClassVar, TypeAlias

from contracts.core.geometry import FrameId, Pose3, Twist3
from contracts.core.primitives import ActionInstanceId, EffectId, RunId, SchemaVersion
from contracts.core.time import TimePoint


class EffectMode(str, Enum):
    ONE_SHOT = "ONE_SHOT"
    CONTINUOUS = "CONTINUOUS"


@dataclass(frozen=True, slots=True)
class ArmEffect:
    mode: ClassVar[EffectMode] = EffectMode.ONE_SHOT


@dataclass(frozen=True, slots=True)
class DisarmEffect:
    mode: ClassVar[EffectMode] = EffectMode.ONE_SHOT


@dataclass(frozen=True, slots=True)
class TakeoffEffect:
    height_m: float
    mode: ClassVar[EffectMode] = EffectMode.ONE_SHOT

    def __post_init__(self) -> None:
        if isinstance(self.height_m, bool) or not isinstance(self.height_m, (int, float)) or not math.isfinite(self.height_m) or self.height_m <= 0:
            raise ValueError("height_m must be a finite positive SI distance")


@dataclass(frozen=True, slots=True)
class LandEffect:
    mode: ClassVar[EffectMode] = EffectMode.ONE_SHOT


@dataclass(frozen=True, slots=True)
class ModeEffect:
    native_mode: str
    mode: ClassVar[EffectMode] = EffectMode.ONE_SHOT

    def __post_init__(self) -> None:
        if not isinstance(self.native_mode, str) or not self.native_mode.strip():
            raise ValueError("native_mode must be non-empty")


@dataclass(frozen=True, slots=True)
class PoseTargetEffect:
    frame_id: FrameId
    target_pose: Pose3
    stream_id: str
    mode: ClassVar[EffectMode] = EffectMode.CONTINUOUS

    def __post_init__(self) -> None:
        if not isinstance(self.frame_id, FrameId):
            object.__setattr__(self, "frame_id", FrameId(self.frame_id))
        if not isinstance(self.target_pose, Pose3):
            raise TypeError("target_pose must be Pose3")
        if not isinstance(self.stream_id, str) or not self.stream_id.strip():
            raise ValueError("stream_id must be non-empty")


@dataclass(frozen=True, slots=True)
class TwistTargetEffect:
    frame_id: FrameId
    target_twist: Twist3
    stream_id: str
    mode: ClassVar[EffectMode] = EffectMode.CONTINUOUS

    def __post_init__(self) -> None:
        if not isinstance(self.frame_id, FrameId):
            object.__setattr__(self, "frame_id", FrameId(self.frame_id))
        if not isinstance(self.target_twist, Twist3):
            raise TypeError("target_twist must be Twist3")
        if not isinstance(self.stream_id, str) or not self.stream_id.strip():
            raise ValueError("stream_id must be non-empty")


@dataclass(frozen=True, slots=True)
class StopMotionEffect:
    stream_id: str
    mode: ClassVar[EffectMode] = EffectMode.ONE_SHOT

    def __post_init__(self) -> None:
        if not isinstance(self.stream_id, str) or not self.stream_id.strip():
            raise ValueError("stream_id must be non-empty")


VehicleEffect: TypeAlias = (
    ArmEffect | DisarmEffect | TakeoffEffect | LandEffect | ModeEffect
    | PoseTargetEffect | TwistTargetEffect | StopMotionEffect
)


@dataclass(frozen=True, slots=True)
class EffectEnvelope:
    schema_version: SchemaVersion
    effect_id: EffectId
    run_id: RunId
    action_instance_id: ActionInstanceId
    created_at: TimePoint
    deadline: TimePoint
    effect: VehicleEffect

    def __post_init__(self) -> None:
        for name, kind in (("effect_id", EffectId), ("run_id", RunId), ("action_instance_id", ActionInstanceId)):
            value = getattr(self, name)
            if not isinstance(value, kind):
                object.__setattr__(self, name, kind(value))
        if not isinstance(self.schema_version, SchemaVersion):
            raise TypeError("schema_version must be SchemaVersion")
        if not isinstance(self.created_at, TimePoint) or not isinstance(self.deadline, TimePoint):
            raise TypeError("effect times must be TimePoint values")
        if self.deadline.elapsed_ns_since(self.created_at) <= 0:
            raise ValueError("effect deadline must follow creation")
        if not isinstance(self.effect, (ArmEffect, DisarmEffect, TakeoffEffect, LandEffect, ModeEffect, PoseTargetEffect, TwistTargetEffect, StopMotionEffect)):
            raise TypeError("effect must be a typed VehicleEffect")
