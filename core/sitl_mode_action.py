"""One-shot, disarmed SITL mode Action with read-only Effect feedback."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.decision import (
    ActionDecision, ActionOutcome, ActionSpec, EffectPhase, EffectResult,
    ExitDecision, ExitReason,
)
from contracts.effects.vehicle import ArmEffect, DisarmEffect, ModeEffect
from contracts.world.models import WorldSnapshot


@dataclass(frozen=True, slots=True)
class SitlModeParameters:
    native_mode: str
    custom_mode_id: int


SITL_MODE_SPEC = ActionSpec("sitl.unarmed_mode", SitlModeParameters,
                            effect_types=(ModeEffect,), effect_ttl_ns=5_000_000_000)


class _SitlModeInstance:
    def __init__(self, parameters: SitlModeParameters) -> None:
        self._parameters = parameters
        self._requested = False

    def tick(self, snapshot: WorldSnapshot) -> ActionDecision:
        return self.tick_with_results(snapshot, ())

    def tick_with_results(self, snapshot: WorldSnapshot,
                          results: tuple[EffectResult, ...]) -> ActionDecision:
        vehicle = snapshot.vehicle
        if vehicle is None or vehicle.operation.armed:
            return ActionDecision(ActionOutcome.FAILED, error="disarmed fresh vehicle state required")
        if not self._requested:
            self._requested = True
            return ActionDecision(ActionOutcome.RUNNING, (ModeEffect(self._parameters.native_mode),))
        if not results:
            return ActionDecision(ActionOutcome.RUNNING)
        result = results[-1]
        if result.phase in (EffectPhase.REJECTED, EffectPhase.UNKNOWN, EffectPhase.CANCELLED):
            return ActionDecision(ActionOutcome.FAILED, error=result.reason or result.phase.value)
        if result.phase is EffectPhase.COMPLETED:
            if vehicle.operation.native_mode == f"ARDUPILOT_CUSTOM_{self._parameters.custom_mode_id}":
                return ActionDecision(ActionOutcome.SUCCEEDED, result={"mode": self._parameters.native_mode})
        return ActionDecision(ActionOutcome.RUNNING)

    def exit(self, snapshot: WorldSnapshot, reason: ExitReason) -> ExitDecision:
        return ExitDecision(True)


class SitlModeAction:
    def start(self, parameters: SitlModeParameters, snapshot: WorldSnapshot) -> _SitlModeInstance:
        return _SitlModeInstance(parameters)


SITL_ARM_SPEC = ActionSpec("sitl.arm", SitlModeParameters,
                           effect_types=(ArmEffect,), effect_ttl_ns=5_000_000_000)
SITL_DISARM_SPEC = ActionSpec("sitl.disarm", SitlModeParameters,
                              effect_types=(DisarmEffect,), effect_ttl_ns=5_000_000_000)


class _SitlArmingInstance:
    def __init__(self, parameters: SitlModeParameters, *, arm: bool) -> None:
        self._parameters = parameters
        self._arm = arm
        self._requested = False

    def tick(self, snapshot: WorldSnapshot) -> ActionDecision:
        return self.tick_with_results(snapshot, ())

    def tick_with_results(self, snapshot: WorldSnapshot,
                          results: tuple[EffectResult, ...]) -> ActionDecision:
        vehicle = snapshot.vehicle
        if vehicle is None:
            return ActionDecision(ActionOutcome.FAILED, error="fresh vehicle state required")
        target_mode = f"ARDUPILOT_CUSTOM_{self._parameters.custom_mode_id}"
        if self._arm and vehicle.operation.native_mode != target_mode:
            return ActionDecision(ActionOutcome.FAILED, error="target mode not observed")
        if not self._requested:
            if vehicle.operation.armed == self._arm:
                return ActionDecision(ActionOutcome.FAILED, error="unexpected initial armed state")
            self._requested = True
            return ActionDecision(ActionOutcome.RUNNING, (ArmEffect() if self._arm else DisarmEffect(),))
        if not results:
            return ActionDecision(ActionOutcome.RUNNING)
        result = results[-1]
        if result.phase in (EffectPhase.REJECTED, EffectPhase.UNKNOWN, EffectPhase.CANCELLED):
            return ActionDecision(ActionOutcome.FAILED, error=result.reason or result.phase.value)
        if result.phase is EffectPhase.COMPLETED and vehicle.operation.armed == self._arm:
            return ActionDecision(ActionOutcome.SUCCEEDED, result={"armed": self._arm})
        return ActionDecision(ActionOutcome.RUNNING)

    def exit(self, snapshot: WorldSnapshot, reason: ExitReason) -> ExitDecision:
        return ExitDecision(True)


class SitlArmAction:
    def start(self, parameters: SitlModeParameters, snapshot: WorldSnapshot) -> _SitlArmingInstance:
        return _SitlArmingInstance(parameters, arm=True)


class SitlDisarmAction:
    def start(self, parameters: SitlModeParameters, snapshot: WorldSnapshot) -> _SitlArmingInstance:
        return _SitlArmingInstance(parameters, arm=False)
