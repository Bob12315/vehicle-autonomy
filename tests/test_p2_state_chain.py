"""Offline Sensor/Vehicle -> WorldSnapshot behavior and safety boundaries."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from application.state_chain import OfflineStateChain
from contracts.core.geometry import Pose3, Quaternion, Vector3
from contracts.core.primitives import ResourceVersion, SchemaVersion
from contracts.core.quality import FreshnessState, QualityState
from contracts.core.serialization import to_json_value
from contracts.core.stamped import Stamped
from contracts.core.time import TimePoint
from contracts.localization.models import LocalizationEstimate
from contracts.sensor import DetectedObject, Observation
from contracts.vehicle.models import VehicleHealth, VehicleStateSnapshot
from localization.reported import ReportedPoseLocalization
from sensors.fake import FakeDetectionSensor
from vehicles.fake import FakeVehicleStateSource
from world_model import FreshnessLimits, WorldModel


UTC = datetime(2026, 1, 1, tzinfo=timezone.utc)


def at(ns: int, domain: str = "offline") -> TimePoint:
    return TimePoint(ns, UTC, domain)


def pose() -> Pose3:
    return Pose3(Vector3(1, 2, 3), Quaternion(0, 0, 0, 1))


def states(snapshot):
    return {entry.component_id: entry for entry in snapshot.freshness}


class P2StateChainTests(unittest.TestCase):
    def setUp(self):
        self.vehicle = FakeVehicleStateSource("vehicle-a", "vehicle-generation")
        self.sensor = FakeDetectionSensor("fake-camera")
        self.localization = ReportedPoseLocalization("fc-projection")
        self.model = WorldModel("world-generation", FreshnessLimits(100, 100, 100))

    def test_end_to_end_publication_preserves_time_frame_and_provenance(self):
        vehicle_state = self.vehicle.publish(
            published_at=at(20), reported_pose=Stamped("odom", at(10), pose()),
            quality=QualityState.DEGRADED,
        )
        detection = self.sensor.observe(
            object_id="marker-1", label="marker", position=Vector3(4, 5, 6),
            confidence=0.8, frame_id="camera_down_optical",
            captured_at=at(12), received_at=at(18),
        )
        chain = OfflineStateChain(self.vehicle, self.localization, self.model)
        reader = chain.world_query()
        self.assertIsNone(reader.snapshot())
        published = chain.collect_and_publish(at(25), (detection,))
        self.assertIs(reader.snapshot(), published)
        self.assertEqual(published.version, ResourceVersion("world-generation", 1))
        self.assertEqual(published.vehicle.reported_pose.frame_id, "odom")
        self.assertEqual(published.localization.pose.frame_id, "odom")
        self.assertIsNot(published.localization, published.vehicle)
        self.assertEqual(published.objects[0].position.frame_id, "camera_down_optical")
        self.assertEqual(published.objects[0].position.captured_at, at(12))
        self.assertEqual(published.objects[0].source_observation_id, detection.observation_id)
        self.assertEqual(states(published)["vehicle"].age_ns, 15)
        self.assertEqual(states(published)["localization"].age_ns, 15)
        self.assertEqual(states(published)["objects"].age_ns, 13)
        self.assertEqual({entry.resource_type for entry in published.dependencies},
                         {"VehicleState", "Localization", "Observation"})
        self.assertEqual(json.loads(json.dumps(to_json_value(published)))["objects"][0]["label"], "marker")
        self.assertFalse(hasattr(reader, "update_vehicle"))
        self.assertFalse(hasattr(reader, "ingest_observation"))
        with self.assertRaises(FrozenInstanceError):
            published.vehicle = None
        self.vehicle.clear()
        missing = chain.collect_and_publish(at(26))
        self.assertIsNone(missing.vehicle)
        self.assertIsNone(missing.localization)
        self.assertEqual(states(missing)["vehicle"].state, FreshnessState.UNKNOWN)
        self.assertIs(reader.snapshot(), missing)
        self.assertIsNot(published, missing)

    def test_missing_stale_and_future_inputs_are_explicit(self):
        empty = self.model.publish(at(100))
        self.assertIsNone(empty.vehicle)
        self.assertIsNone(empty.localization)
        self.assertEqual(empty.objects, ())
        self.assertTrue(all(value.state is FreshnessState.UNKNOWN for value in states(empty).values()))

        recent_publication_old_capture = self.vehicle.publish(
            published_at=at(199), reported_pose=Stamped("odom", at(10), pose()),
        )
        self.model.update_vehicle(recent_publication_old_capture)
        self.model.update_localization(self.localization.estimate(recent_publication_old_capture))
        self.model.ingest_observation(self.sensor.observe(
            object_id="old", label="old", position=Vector3(0, 0, 0), confidence=1,
            frame_id="map", captured_at=at(10), received_at=at(199),
        ))
        stale = self.model.publish(at(200))
        self.assertIsNone(stale.vehicle)
        self.assertIsNone(stale.localization)
        self.assertEqual(stale.objects, ())
        self.assertEqual(states(stale)["vehicle"].state, FreshnessState.STALE)
        self.assertEqual(states(stale)["localization"].state, FreshnessState.STALE)
        self.assertEqual(states(stale)["objects"].state, FreshnessState.STALE)
        self.assertEqual(len(stale.dependencies), 3)
        self.assertEqual(empty.version.revision, 1)
        self.assertEqual(stale.version.revision, 2)
        self.assertIsNot(empty, stale)
        self.assertIsNone(empty.vehicle)

        future_vehicle = self.vehicle.publish(published_at=at(220), reported_pose=Stamped("odom", at(220), pose()))
        self.model.update_vehicle(future_vehicle)
        future = self.model.publish(at(210))
        self.assertEqual(states(future)["vehicle"].state, FreshnessState.UNKNOWN)
        self.assertEqual(states(future)["vehicle"].reason, "future_timestamp")
        self.assertIsNone(future.vehicle)

    def test_clock_domain_and_quality_are_independent(self):
        other_domain = self.vehicle.publish(published_at=at(10, "other"), reported_pose=Stamped("odom", at(9, "other"), pose()))
        self.model.update_vehicle(other_domain)
        unknown = self.model.publish(at(20))
        self.assertEqual(states(unknown)["vehicle"].reason, "clock_domain_mismatch")
        self.assertIsNone(unknown.vehicle)

        invalid = self.vehicle.publish(published_at=at(30), reported_pose=Stamped("odom", at(29), pose()), quality=QualityState.INVALID)
        self.model.update_vehicle(invalid)
        self.assertIsNone(self.localization.estimate(invalid))
        fresh_but_invalid = self.model.publish(at(31))
        self.assertEqual(states(fresh_but_invalid)["vehicle"].state, FreshnessState.FRESH)
        self.assertIsNone(fresh_but_invalid.vehicle)
        self.assertEqual(fresh_but_invalid.dependencies[0].version, invalid.version)

    def test_thresholds_and_regression_checks(self):
        state = self.vehicle.publish(published_at=at(10))
        self.model.update_vehicle(state)
        at_limit = self.model.publish(at(110))
        self.assertEqual(states(at_limit)["vehicle"].state, FreshnessState.FRESH)
        expired = self.model.publish(at(111))
        self.assertEqual(states(expired)["vehicle"].state, FreshnessState.STALE)
        with self.assertRaises(ValueError):
            self.model.publish(at(109))
        older = VehicleStateSnapshot(SchemaVersion(1, 0), "vehicle-a", ResourceVersion("vehicle-generation", 0), at(9), VehicleHealth(QualityState.VALID))
        with self.assertRaises(ValueError):
            self.model.update_vehicle(older)
        reused = VehicleStateSnapshot(SchemaVersion(1, 0), "vehicle-a", state.version, at(11), VehicleHealth(QualityState.VALID))
        with self.assertRaises(ValueError):
            self.model.update_vehicle(reused)
        impossible = VehicleStateSnapshot(SchemaVersion(1, 0), "vehicle-a", ResourceVersion("vehicle-generation", 2), at(20),
                                          VehicleHealth(QualityState.VALID), reported_pose=Stamped("odom", at(21), pose()))
        with self.assertRaises(ValueError):
            self.model.update_vehicle(impossible)
        with self.assertRaises(ValueError):
            FreshnessLimits(0, 1, 1)

    def test_sensor_observation_validation_and_versioning(self):
        with self.assertRaises(ValueError):
            self.sensor.observe(object_id="x", label="x", position=Vector3(0, 0, 0), confidence=1,
                                frame_id="map", captured_at=at(20), received_at=at(19))
        first = self.sensor.observe(object_id="x", label="x", position=Vector3(0, 0, 0), confidence=1,
                                    frame_id="map", captured_at=at(20), received_at=at(21))
        self.model.ingest_observation(first)
        with self.assertRaises(ValueError):
            self.model.ingest_observation(Observation("old", SchemaVersion(1, 0), "fake-camera", 0,
                                                      at(20), at(21), QualityState.VALID,
                                                      DetectedObject("x", "x", Vector3(0, 0, 0), 1), "map"))
        with self.assertRaises(ValueError):
            self.model.ingest_observation(Observation("unframed", SchemaVersion(1, 0), "other", 1,
                                                      at(20), at(21), QualityState.VALID,
                                                      DetectedObject("x", "x", Vector3(0, 0, 0), 1)))
        second = self.sensor.observe(object_id="x", label="new", position=Vector3(1, 0, 0), confidence=0.9,
                                     frame_id="base_link", captured_at=at(25), received_at=at(26))
        self.model.ingest_observation(second)
        world = self.model.publish(at(30))
        self.assertEqual(len(world.objects), 1)
        self.assertEqual(world.objects[0].label, "new")
        self.assertEqual(world.objects[0].position.frame_id, "base_link")
        self.assertEqual(world.dependencies[0].version.revision, second.sequence)

    def test_world_state_has_no_control_fields(self):
        forbidden = {"send_enabled", "control_allowed", "authorization", "lease", "command_port"}
        self.assertFalse(forbidden & {field.name for field in fields(type(self.model.publish(at(1))))})

    def test_state_chain_has_no_command_dependency(self):
        root = Path(__file__).resolve().parents[1]
        paths = (
            "application/state_chain.py", "world_model/service.py", "world_model/models.py",
            "sensors/fake.py", "vehicles/fake.py", "localization/reported.py",
        )
        for path in paths:
            tree = ast.parse((root / path).read_text(encoding="utf-8"))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    imports.append((node.module or "", {alias.name for alias in node.names}))
                elif isinstance(node, ast.Import):
                    imports.extend((alias.name, set()) for alias in node.names)
            self.assertFalse(any(module.startswith(("core.execution", "contracts.vehicle.command", "protocols", "pymavlink", "legacy"))
                                 or (module == "contracts.vehicle.ports" and "VehicleCommandPort" in names)
                                 for module, names in imports), path)


if __name__ == "__main__":
    unittest.main()
