"""Finite Rover mission for an explicitly admitted path."""
from actions.basic import BasicParameters
from actions.path_following import SPEC
from contracts.decision import MissionPlan, MissionStep
from core.sitl_mode_action import SITL_MODE_SPEC, SitlModeParameters


def build(parameters, mode_id):
    basic = BasicParameters("rover", parameters.environment)
    return MissionPlan("follow_path", (
        MissionStep("mode", SITL_MODE_SPEC.name, SitlModeParameters("GUIDED", mode_id)),
        MissionStep("arm", "basic.arm", basic),
        MissionStep("follow_path", SPEC.name, parameters),
        MissionStep("disarm", "basic.disarm", basic),
    ))
