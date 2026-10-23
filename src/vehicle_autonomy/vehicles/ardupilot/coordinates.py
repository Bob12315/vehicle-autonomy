"""ArduPilot NED/FRD to framework ENU/FLU rotation boundary."""
import math
from vehicle_autonomy.contracts.core.geometry import Quaternion, Vector3
from vehicle_autonomy.world.transform.tree import multiply_quaternions

_SQRT_HALF = math.sqrt(0.5)
_NED_TO_ENU = Quaternion(_SQRT_HALF, _SQRT_HALF, 0, 0)
_FLU_TO_FRD = Quaternion(1, 0, 0, 0)


def _ned_to_enu(north: float, east: float, down: float) -> Vector3:
    return Vector3(east, north, -down)


def _euler_frd_ned_to_flu_enu(roll: float, pitch: float, yaw: float) -> Quaternion:
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    original = Quaternion(
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )
    return multiply_quaternions(multiply_quaternions(_NED_TO_ENU, original), _FLU_TO_FRD)


