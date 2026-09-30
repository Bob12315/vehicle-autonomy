"""P1 invariant checks for the frozen V1 foundation contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, fields
from datetime import datetime, timedelta, timezone
import json
import math
import unittest

from contracts.core.geometry import FrameId, GeoPoint, Pose3, Quaternion, Transform3, Twist3, Vector3
from contracts.core.primitives import (
    ResourceVersion, SchemaVersion, VehicleId, freeze_json, thaw_json,
)
from contracts.core.quality import ComponentFreshness, FreshnessState, QualityState
from contracts.core.serialization import to_json_value
from contracts.core.stamped import Stamped
from contracts.core.time import TimeFacts, TimePoint
from contracts.effects import (
    ArmEffect, EffectEnvelope, EffectMode, PoseTargetEffect, StopMotionEffect,
    TakeoffEffect, TwistTargetEffect,
)
from contracts.localization.models import LocalizationEstimate
from contracts.sensor.observation import Observation
from contracts.vehicle.command import (
    ArmCommand, CancelCommandRequest, CommandPhase, CommandReceipt, CommandStatus,
    VehicleCommandEnvelope,
)
from contracts.vehicle.models import BatteryState, VehicleHealth, VehicleStateSnapshot
from contracts.vehicle.ports import VehicleCommandPort, VehicleStatePort
from contracts.world.models import ResourceDependency, ResourceReference, WorldSnapshot
from contracts.world.ports import LocalizationPort, TransformResolver, WorldQueryPort


def instant(ns: int = 10, domain: str = "clock-a") -> TimePoint:
    return TimePoint(ns, datetime(2026, 1, 1, tzinfo=timezone.utc), domain)


def pose() -> Pose3:
    return Pose3(Vector3(1, 2, 3), Quaternion(0, 0, 0, 1))


@dataclass(frozen=True, slots=True)
class TypedDetection:
    label: str
    position: Vector3


class PrimitiveTests(unittest.TestCase):
    def test_identity_and_versions(self):
        self.assertEqual(VehicleId("v1"), "v1")
        with self.assertRaises(ValueError):
            VehicleId(" ")
        self.assertEqual(str(SchemaVersion.parse("1.2")), "1.2")
        for raw in ("1", "1.-1", "a.b"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                SchemaVersion.parse(raw)
        with self.assertRaises(ValueError):
            SchemaVersion(True, 0)
        self.assertEqual(ResourceVersion("generation-a", 2).revision, 2)
        with self.assertRaises(ValueError):
            ResourceVersion("generation-a", -1)

    def test_frozen_json_is_canonical_and_detached(self):
        original = {"z": [1, {"a": True}], "a": "text"}
        frozen = freeze_json(original)
        original["z"][1]["a"] = False
        self.assertEqual(thaw_json(frozen), {"a": "text", "z": [1, {"a": True}]})
        self.assertEqual(to_json_value(frozen), {"a": "text", "z": [1, {"a": True}]})
        self.assertEqual(list(frozen), ["a", "z"])
        thawed = thaw_json(frozen)
        thawed["z"].append(9)
        self.assertEqual(thaw_json(frozen)["z"], [1, {"a": True}])
        with self.assertRaises(TypeError):
            frozen["z"] = ()
        for value in (math.nan, math.inf, {1: "bad"}, {"x": object()}):
            with self.subTest(value=repr(value)), self.assertRaises((TypeError, ValueError)):
                freeze_json(value)

    def test_time_facts_and_clock_domains(self):
        earlier, later = instant(10), instant(15)
        self.assertEqual(later.elapsed_ns_since(earlier), 5)
        self.assertTrue(earlier < later)
        facts = TimeFacts(captured_at=earlier, received_at=later, published_at=instant(20))
        self.assertEqual(facts.captured_at.monotonic_ns, 10)
        self.assertEqual(facts.published_at.monotonic_ns, 20)
        with self.assertRaises(ValueError):
            TimePoint(-1, earlier.utc, "clock-a")
        with self.assertRaises(ValueError):
            TimePoint(1, datetime(2026, 1, 1), "clock-a")
        with self.assertRaises(ValueError):
            TimePoint(1, earlier.utc, " ")
        with self.assertRaises(ValueError):
            later.elapsed_ns_since(instant(10, "clock-b"))
        with self.assertRaises(ValueError):
            _ = earlier < instant(10, "clock-b")
        offset = TimePoint(1, datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8))), "clock-a")
        self.assertEqual(offset.utc, earlier.utc)

    def test_geometry_and_frame_validation(self):
        self.assertEqual(FrameId("camera_down_optical"), "camera_down_optical")
        with self.assertRaises(ValueError):
            FrameId("")
        for maker in (
            lambda: Vector3(math.nan, 0, 0),
            lambda: Quaternion(math.inf, 0, 0, 1),
            lambda: Quaternion(0, 0, 0, 2),
            lambda: GeoPoint(91, 0, 0),
            lambda: GeoPoint(0, -181, 0),
            lambda: GeoPoint(0, 0, math.inf),
        ):
            with self.subTest(maker=maker), self.assertRaises(ValueError):
                maker()
        self.assertEqual(Transform3(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1)).translation.x, 0)
        self.assertEqual(Stamped("map", instant(), pose()).frame_id, "map")
        with self.assertRaises(ValueError):
            Stamped("", instant(), pose())
        with self.assertRaises(TypeError):
            Stamped("map", instant(), [1, 2, 3])


class StateContractTests(unittest.TestCase):
    def test_observation_requires_typed_immutable_data_and_frame(self):
        args = dict(observation_id="obs-1", schema_version=SchemaVersion(1, 0), producer_id="detector", sequence=1,
                    captured_at=instant(10), received_at=instant(11), quality=QualityState.DEGRADED)
        found = Observation(**args, data=TypedDetection("vehicle", Vector3(1, 0, 0)), frame_id="map")
        self.assertEqual(found.frame_id, "map")
        with self.assertRaises(ValueError):
            Observation(**args, data=pose())
        for data in ({"x": 1}, [1], "untyped"):
            with self.subTest(data=data), self.assertRaises(TypeError):
                Observation(**args, data=data)
        with self.assertRaises(ValueError):
            Observation(**{**args, "sequence": -1}, data=found.data, frame_id="map")
        with self.assertRaises(FrozenInstanceError):
            found.sequence = 2

    def test_vehicle_localization_world_are_distinct_immutable_publications(self):
        reported = Stamped("odom", instant(), pose())
        estimate = Stamped("map", instant(), pose())
        vehicle = VehicleStateSnapshot(SchemaVersion(1, 0), "vehicle-a", ResourceVersion("vehicle", 1), instant(20),
                                       VehicleHealth(QualityState.VALID), reported_pose=reported,
                                       battery=BatteryState(12.0, 1.0, 50.0))
        localization = LocalizationEstimate(SchemaVersion(1, 0), ResourceVersion("localization", 2), "fused",
                                            instant(21), estimate, QualityState.DEGRADED)
        world = WorldSnapshot(SchemaVersion(1, 0), "snapshot-a", ResourceVersion("world", 3), instant(22),
                              vehicle=vehicle, localization=localization,
                              objects=(TypedDetection("marker", Vector3(0, 1, 0)),),
                              map=ResourceReference("map-a", ResourceVersion("map", 4)),
                              freshness=(ComponentFreshness("localization", FreshnessState.FRESH, 1),),
                              dependencies=(ResourceDependency("VehicleState", "vehicle-a", vehicle.version),
                                            ResourceDependency("Localization", "fused", localization.version)))
        self.assertEqual(world.vehicle.reported_pose.frame_id, "odom")
        self.assertEqual(world.localization.pose.frame_id, "map")
        self.assertEqual(world.version.revision, 3)
        self.assertEqual(world.dependencies[0].version, vehicle.version)
        self.assertFalse({"send_enabled", "control_allowed", "authorization", "source", "lease"} &
                         {field.name for field in fields(VehicleStateSnapshot)})
        self.assertFalse({"send_enabled", "authorization", "lease"} &
                         {field.name for field in fields(WorldSnapshot)})
        with self.assertRaises(FrozenInstanceError):
            world.objects = ()
        with self.assertRaises(TypeError):
            WorldSnapshot(SchemaVersion(1, 0), "s", ResourceVersion("world", 1), instant(), objects=({"mutable": 1},))
        with self.assertRaises(ValueError):
            WorldSnapshot(SchemaVersion(1, 0), "s", ResourceVersion("world", 1), instant(),
                          freshness=(ComponentFreshness("vehicle", FreshnessState.STALE, 1),
                                     ComponentFreshness("vehicle", FreshnessState.FRESH, 0)))

    def test_serialization_of_versioned_values(self):
        value = VehicleStateSnapshot(SchemaVersion(1, 0), "vehicle-a", ResourceVersion("vgen", 2), instant(),
                                     VehicleHealth(QualityState.UNAVAILABLE))
        encoded = json.loads(json.dumps(to_json_value(value), sort_keys=True))
        self.assertEqual(encoded["schema_version"], {"major": 1, "minor": 0})
        self.assertEqual(encoded["version"], {"generation_id": "vgen", "revision": 2})
        self.assertEqual(encoded["health"]["quality"], "UNAVAILABLE")
        self.assertEqual(encoded["published_at"]["utc"], "2026-01-01T00:00:00Z")


class EffectCommandTests(unittest.TestCase):
    def test_effect_is_a_request_and_command_is_a_separate_type(self):
        effect = EffectEnvelope(SchemaVersion(1, 0), "effect-a", "run-a", "action-a", instant(10), instant(20), ArmEffect())
        command = VehicleCommandEnvelope(SchemaVersion(1, 0), "command-a", "run-a", "lease-a", 1, 1,
                                         "link-a", instant(10), instant(20), 0, "idem-a", ArmCommand())
        self.assertEqual(effect.effect.mode, EffectMode.ONE_SHOT)
        self.assertNotEqual(type(effect.effect), type(command.command))
        self.assertFalse({"authorization_generation", "send_generation", "lease_id", "expected_link_session_id"} &
                         {field.name for field in fields(EffectEnvelope)})
        self.assertEqual(command.authorization_generation, 1)
        with self.assertRaises(TypeError):
            VehicleCommandEnvelope(SchemaVersion(1, 0), "command-a", "run-a", "lease-a", 1, 1,
                                   "link-a", instant(10), instant(20), 0, "idem-a", effect.effect)
        with self.assertRaises(ValueError):
            EffectEnvelope(SchemaVersion(1, 0), "effect-a", "run-a", "action-a", instant(20), instant(10), ArmEffect())
        with self.assertRaises(ValueError):
            VehicleCommandEnvelope(SchemaVersion(1, 0), "command-a", "run-a", "lease-a", -1, 1,
                                   "link-a", instant(10), instant(20), 0, "idem-a", ArmCommand())

    def test_effect_spatial_and_continuous_semantics(self):
        target = TwistTargetEffect("base_link", Twist3(Vector3(1, 0, 0), Vector3(0, 0, 0)), "stream-a")
        self.assertEqual(target.mode, EffectMode.CONTINUOUS)
        self.assertEqual(StopMotionEffect("stream-a").mode, EffectMode.ONE_SHOT)
        self.assertEqual(PoseTargetEffect("map", pose(), "stream-a").frame_id, "map")
        with self.assertRaises(ValueError):
            TwistTargetEffect("", target.target_twist, "stream-a")
        with self.assertRaises(ValueError):
            TakeoffEffect(math.inf)
        with self.assertRaises(ValueError):
            StopMotionEffect("")

    def test_ports_are_narrow_contracts(self):
        self.assertEqual({name for name in vars(VehicleCommandPort) if not name.startswith("_")},
                         {"submit", "cancel", "status"})
        self.assertEqual({name for name in vars(VehicleStatePort) if not name.startswith("_")}, {"snapshot"})
        self.assertEqual({name for name in vars(LocalizationPort) if not name.startswith("_")}, {"current"})
        self.assertEqual({name for name in vars(WorldQueryPort) if not name.startswith("_")}, {"snapshot"})
        self.assertEqual({name for name in vars(TransformResolver) if not name.startswith("_")}, {"transform"})
        self.assertEqual(CommandReceipt("c", CommandPhase.ACCEPTED).phase, CommandPhase.ACCEPTED)
        self.assertEqual(CancelCommandRequest("c", instant()).command_id, "c")
        self.assertEqual(CommandStatus("c", CommandPhase.TRANSMITTED, instant()).phase, CommandPhase.TRANSMITTED)


if __name__ == "__main__":
    unittest.main()
