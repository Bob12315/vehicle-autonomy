"""Named fake Action registry; every update fails before emitting an Effect."""

from __future__ import annotations

from typing import Any

from missions.action_definition_builder import _definition
from missions.common.actions.base import ActionModule
from missions.common.actions.result import ActionResult


class _UnavailableRoverAction(ActionModule):
    def __init__(self) -> None:
        self.reset()

    def start(self, params: dict[str, Any] | None = None) -> None:
        self.params = dict(params or {})
        self.started = True

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        return ActionResult(failed=True, reason="fake_rover_no_control_backend")

    def stop(self) -> None:
        self.started = False

    def reset(self) -> None:
        self.params: dict[str, Any] = {}
        self.started = False


class StopAction(_UnavailableRoverAction):
    pass


class DriveVelocityAction(_UnavailableRoverAction):
    pass


class GotoGroundAction(_UnavailableRoverAction):
    pass


ROVER_ACTION_DEFINITIONS = (
    _definition("stop", StopAction, "Fake Rover stop capability; no command backend.",
                properties={}),
    _definition("drive_velocity", DriveVelocityAction,
                "Fake Rover forward/yaw target; no command backend.",
                properties={"forward_mps": {"type": "number"},
                            "yaw_rate_rad_s": {"type": "number"}},
                parameter_schema_extra={"required": ["forward_mps", "yaw_rate_rad_s"]}),
    _definition("goto_ground", GotoGroundAction,
                "Fake Rover local ground target; no command backend.",
                properties={"north_m": {"type": "number"},
                            "east_m": {"type": "number"}},
                parameter_schema_extra={"required": ["north_m", "east_m"]}),
)
