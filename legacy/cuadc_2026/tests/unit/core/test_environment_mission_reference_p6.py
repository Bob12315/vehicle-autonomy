import pytest

from contracts.core.common import freeze_json, thaw_json
from contracts.environment import CoordinateReference, EnvironmentProfile, EnvironmentSnapshot, NamedLocation
from contracts.platform.common import ResourceVersion
from missions.core.blackboard import BlackboardSnapshot, resolve_compiled_parameters
from missions.core.mission_compiler import MissionCompiler


def test_mission_environment_location_reference_is_resolved_at_runtime() -> None:
    compiler = object.__new__(MissionCompiler)
    compiled = freeze_json(compiler._compile_value({
        "x": "$environment.locations.drop_center.x",
        "location": "$environment.locations.drop_center",
    }))
    environment = EnvironmentSnapshot(
        EnvironmentProfile("example", "Example", "local"), ResourceVersion("example", 1),
        CoordinateReference("local", confirmed=True),
        (NamedLocation("drop_center", "local", 4.0, 8.0, 2.0),),
    )
    blackboard = BlackboardSnapshot(ResourceVersion("blackboard", 0))
    resolved = thaw_json(resolve_compiled_parameters(compiled, blackboard, environment))
    assert resolved == {"x": 4.0, "location": {
        "frame": "local", "x": 4.0, "y": 8.0, "altitude_m": 2.0,
    }}
    with pytest.raises(KeyError, match="environment_unavailable"):
        resolve_compiled_parameters(compiled, blackboard)
    with pytest.raises(KeyError, match="drop_center"):
        resolve_compiled_parameters(compiled, blackboard,
                                    EnvironmentSnapshot(environment.profile, environment.version,
                                                        environment.reference))
    with pytest.raises(ValueError, match="unsupported environment reference"):
        compiler._compile_value("$environment.zones.drop")
