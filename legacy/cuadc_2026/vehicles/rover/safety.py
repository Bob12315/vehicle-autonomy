"""Fake Rover policy closes the command path until a real backend is designed."""

from __future__ import annotations

import math
from dataclasses import dataclass

from contracts.core.common import freeze_json
from contracts.core.effects import Effect
from contracts.core.execution import SafetyContext, SafetyDecision, SafetyDisposition


@dataclass(frozen=True, slots=True)
class RoverSafetyConfig:
    revision: str = "fake-v1"
    max_forward_mps: float = 1.0
    max_yaw_rate_rad_s: float = 0.5

    def __post_init__(self) -> None:
        if not self.revision or not all(math.isfinite(value) and value > 0 for value in (
            self.max_forward_mps, self.max_yaw_rate_rad_s,
        )):
            raise ValueError("invalid Rover safety limits")


class RoverSafetyPolicy:
    def __init__(self, config: RoverSafetyConfig = RoverSafetyConfig()) -> None:
        self.config = config

    def evaluate(self, effect: Effect, context: SafetyContext) -> SafetyDecision:
        reason = "send_disabled" if not context.send_enabled else "fake_rover_no_control_backend"
        return SafetyDecision(SafetyDisposition.REJECT, effect, None, reason, freeze_json({}))
