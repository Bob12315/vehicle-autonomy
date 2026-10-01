"""A fresh heartbeat alone must never authorize a motion setpoint."""

from dataclasses import replace
from datetime import datetime, timezone
import unittest

from contracts.core.geometry import FrameId, Pose3, Quaternion, Twist3, Vector3
from contracts.core.primitives import ResourceVersion, SchemaVersion
from contracts.core.quality import ComponentFreshness, FreshnessState, QualityState
from contracts.core.stamped import Stamped
from contracts.core.time import TimePoint
from contracts.effects.vehicle import EffectEnvelope, TwistTargetEffect
from contracts.vehicle.models import VehicleHealth, VehicleOperation, VehicleStateSnapshot
from contracts.world.models import WorldSnapshot
from core.vehicle_safety import SafetyLimits
from deployment.simulation_safety import SimulationSafetyPolicy


def at(ns: int, domain: str = "host") -> TimePoint:
    return TimePoint(ns, datetime(2026, 1, 1, tzinfo=timezone.utc), domain)


class SimulationSafetyTests(unittest.TestCase):
    def setUp(self):
        limits = SafetyLimits(100, 50, 10, -1, 5, 1, 2, 1,
                              frozenset({FrameId("base_link")}), frozenset({"GUIDED"}), -5, 5, -5, 5)
        self.policy = SimulationSafetyPolicy(limits, motion_mode_id=15)
        self.effect = EffectEnvelope(
            SchemaVersion(1, 0), "effect", "run", "action", at(100), at(150),
            TwistTargetEffect("base_link", Twist3(Vector3(.5, 0, 0), Vector3(0, 0, 0)), "drive"),
        )
        pose = Stamped("odom", at(100), Pose3(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1)))
        twist = Stamped("odom", at(100), Twist3(Vector3(0, 0, 0), Vector3(0, 0, 0)))
        vehicle = VehicleStateSnapshot(SchemaVersion(1, 0), "rover", ResourceVersion("v", 1),
                                       at(100), VehicleHealth(QualityState.VALID), pose, twist,
                                       operation=VehicleOperation(armed=True, native_mode="ARDUPILOT_CUSTOM_15"))
        self.world = WorldSnapshot(SchemaVersion(1, 0), "w", ResourceVersion("w", 1), at(100),
                                   vehicle=vehicle,
                                   freshness=(ComponentFreshness("vehicle", FreshnessState.FRESH),))

    def test_fresh_pose_and_twist_allow_motion(self):
        self.assertIsNone(self.policy.evaluate(self.effect, self.world, at(101)))

    def test_missing_stale_future_and_wrong_clock_motion_state(self):
        vehicle = self.world.vehicle
        cases = (
            (replace(vehicle, reported_pose=None), "motion_state_unavailable"),
            (replace(vehicle, reported_twist=replace(vehicle.reported_twist, captured_at=at(1))), "motion_state_stale"),
            (replace(vehicle, reported_pose=replace(vehicle.reported_pose, captured_at=at(102))), "motion_state_stale"),
            (replace(vehicle, reported_pose=replace(vehicle.reported_pose, captured_at=at(100, "other"))),
             "motion_clock_domain_mismatch"),
        )
        for state, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(self.policy.evaluate(self.effect, replace(self.world, vehicle=state), at(101)), reason)

    def test_disarmed_or_wrong_mode_blocks_motion(self):
        state = self.world.vehicle
        for operation, reason in ((VehicleOperation(armed=False, native_mode="ARDUPILOT_CUSTOM_15"),
                                   "motion_requires_armed"),
                                  (VehicleOperation(armed=True, native_mode="ARDUPILOT_CUSTOM_4"),
                                   "motion_requires_guided_mode")):
            with self.subTest(reason=reason):
                self.assertEqual(self.policy.evaluate(self.effect,
                    replace(self.world, vehicle=replace(state, operation=operation)), at(101)), reason)


if __name__ == "__main__":
    unittest.main()
