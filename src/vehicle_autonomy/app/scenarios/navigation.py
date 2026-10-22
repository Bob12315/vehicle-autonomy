"""Finite Rover mission for an explicitly admitted path."""
from vehicle_autonomy.actions.common.basic import BasicParameters
from vehicle_autonomy.actions.navigation.path_following import SPEC
from vehicle_autonomy.contracts.decision import MissionPlan, MissionStep
from vehicle_autonomy.actions.common.sitl_mode import SITL_MODE_SPEC, SitlModeParameters


def build(parameters, mode_id):
    basic = BasicParameters("rover", parameters.environment)
    return MissionPlan("follow_path", (
        MissionStep("mode", SITL_MODE_SPEC.name, SitlModeParameters("GUIDED", mode_id)),
        MissionStep("arm", "basic.arm", basic),
        MissionStep("follow_path", SPEC.name, parameters),
        MissionStep("disarm", "basic.disarm", basic),
    ))
