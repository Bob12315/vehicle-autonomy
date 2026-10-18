"""Content, time, version and epoch boundaries without ROS installed/imported."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from contracts.core.geometry import Pose3, Quaternion, Vector3
from contracts.core.primitives import ResourceVersion
from contracts.core.quality import FreshnessState
from contracts.core.time import TimePoint
from contracts.world.models import ResourceReference
from mapping.clock import RosClockBridge
from mapping.exchange import MappingConfig, MappingInput
from mapping.grid import MapStore, OccupancyGrid, atomic_json, pose_to_json
from world_model import WorldModel, FreshnessLimits


IDENTITY = Pose3(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1))


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name)
        self.now = TimePoint(5_000_000_000, datetime(2026, 10, 19, tzinfo=timezone.utc), "test-clock")
        self.grid = OccupancyGrid("map", .1, 2, 2, IDENTITY, (0, 100, -1, 0))
        self.store = MapStore(self.path / "maps")
        self.digest = self.store.save(self.grid)
        self.reader = MappingInput(MappingConfig(self.path, "test-clock", 1_000_000_000))
        self.document = {"schema": 1, "source": "ros2.slam_toolbox", "source_epoch": "source-A",
            "frame_epoch": "world-A", "clock_domain_id": "test-clock", "published_ns": self.now.monotonic_ns,
            "status": "VALID", "map": {"revision": 1, "sha256": self.digest, "captured_ns": self.now.monotonic_ns - 100_000_000},
            "base_link_in_map": pose_to_json(IDENTITY), "odom_in_map": pose_to_json(IDENTITY)}

    def poll(self, value=None, now=None, epoch="world-A"):
        atomic_json(self.path / "bridge.json", self.document if value is None else value)
        return self.reader.poll(now or self.now, epoch)

    def test_content_roundtrip_and_export_row_order(self):
        self.assertEqual(self.store.load(self.digest), self.grid)
        self.store.export_pgm(self.digest, self.path / "export")
        self.assertTrue((self.path / "export/map.pgm").read_bytes().endswith(bytes([205, 254, 254, 0])))
        self.assertIn("resolution: 0.1", (self.path / "export/map.yaml").read_text())
        (self.path / "maps" / f"{self.digest}.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.store.load(self.digest)

    def test_grid_rejects_invalid_dimensions_cells_and_resolution(self):
        for fields in ({"width": 0}, {"height": 100000}, {"cells": (0, 0)},
                       {"cells": (False, 100, -1, 0)}, {"resolution_m": float("nan")}, {"cells": (101, 0, 0, 0)}):
            with self.assertRaises((ValueError, TypeError)):
                replace(self.grid, **fields)
        with self.assertRaises(ValueError):
            self.store.load("../outside")

    def test_symlink_grid_and_envelope_rejected(self):
        p = self.path / "maps" / f"{self.digest}.json"
        p.rename(self.path / "actual.json")
        p.symlink_to(self.path / "actual.json")
        with self.assertRaises(OSError):
            self.store.load(self.digest)
        (self.path / "bridge.json").symlink_to(self.path / "actual.json")
        self.assertIsNone(self.reader.poll(self.now, "world-A"))

    def test_map_reference_is_timed_and_bound_to_current_epoch(self):
        adopted = self.poll()
        self.assertEqual(adopted.reference.version, ResourceVersion("source-A", 1))
        self.assertEqual(adopted.grid, self.grid)
        self.assertEqual(self.reader.health["age_ns"], 100_000_000)
        self.assertIsNone(self.reader.poll(self.now, "world-B"))
        self.assertFalse(self.reader.health["valid"])

    def test_stale_future_and_clock_mismatch_rejected(self):
        for changes in ({"published_ns": self.now.monotonic_ns+1}, {"clock_domain_id": "another"},
                        {"status": "UNAVAILABLE", "error": "clock paused"}):
            value = deepcopy(self.document);value.update(changes)
            self.assertIsNone(self.poll(value))
        self.assertIsNone(self.poll(now=replace(self.now, monotonic_ns=self.now.monotonic_ns+2_000_000_000)))

    def test_reused_version_cannot_change_pose_content_or_time(self):
        self.assertIsNotNone(self.poll())
        for field in ("pose", "time", "hash"):
            value = deepcopy(self.document)
            if field == "pose":value["base_link_in_map"]["position"][0] = 1
            elif field == "time":value["map"]["captured_ns"] += 1
            else:value["map"]["sha256"] = "0" * 64
            self.assertIsNone(self.poll(value))

    def test_source_restart_cannot_replay_retired_map(self):
        self.assertIsNotNone(self.poll())
        new = deepcopy(self.document);new["source_epoch"] = "source-B"
        self.assertIsNotNone(self.poll(new))
        self.assertIsNone(self.poll(self.document))
        self.assertIn("retired", self.reader.health["error"])

    def test_out_of_order_revision_and_corrupt_envelope_fail_closed(self):
        self.document["map"]["revision"] = 2
        self.assertIsNotNone(self.poll())
        older = deepcopy(self.document);older["map"]["revision"] = 1
        self.assertIsNone(self.poll(older))
        (self.path / "bridge.json").write_text("{" * 17000)
        self.assertIsNone(self.reader.poll(self.now, "world-A"))
        (self.path / "bridge.json").write_text("[" * 1500 + "]" * 1500)
        self.assertIsNone(self.reader.poll(self.now, "world-A"))

    def test_world_map_freshness_and_dependencies(self):
        world = WorldModel("world-A", FreshnessLimits(1_000_000_000, 1_000_000_000, 1_000_000_000, map_ns=1_000_000_000))
        value = self.poll()
        world.update_map(value.reference, value.captured_at)
        fresh = world.publish(self.now)
        self.assertEqual(fresh.map, value.reference)
        self.assertTrue(any(item.resource_type == "Map" and item.version == value.reference.version for item in fresh.dependencies))
        stale = world.publish(replace(self.now, monotonic_ns=self.now.monotonic_ns+2_000_000_000))
        self.assertIsNone(stale.map)
        self.assertEqual(next(f for f in stale.freshness if f.component_id == "map").state, FreshnessState.STALE)
        with self.assertRaises(ValueError):
            world.update_map(value.reference, self.now)
        world.update_map(None)
        self.assertIsNone(world.snapshot().map)

    def test_world_map_rejects_future_and_different_domain(self):
        for stamp in (replace(self.now, clock_domain_id="other"), replace(self.now, monotonic_ns=self.now.monotonic_ns+1)):
            world = WorldModel("world-A", FreshnessLimits(1, 1, 1))
            world.update_map(ResourceReference("map", ResourceVersion("source", 1)), stamp)
            self.assertIsNone(world.publish(self.now).map)


class RosClockTests(unittest.TestCase):
    def test_interpolation_never_extrapolates(self):
        clock = RosClockBridge()
        clock.observe(100_000_000, 1_000_000_000)
        clock.observe(200_000_000, 1_100_000_000)
        self.assertEqual(clock.to_host(150_000_000), 1_050_000_000)
        self.assertEqual(clock.to_ros(1_050_000_000), 150_000_000)
        for stamp in (0, 99_999_999, 200_000_001):
            with self.assertRaises(LookupError):clock.to_host(stamp)

    def test_duplicates_preserve_age_and_backwards_jump_starts_epoch(self):
        clock = RosClockBridge()
        clock.observe(100_000_000, 1_000_000_000)
        epoch = clock.epoch
        clock.observe(100_000_000, 1_100_000_000)
        self.assertEqual(clock.to_host(100_000_000), 1_000_000_000)
        self.assertTrue(clock.observe(50_000_000, 1_200_000_000))
        self.assertNotEqual(clock.epoch, epoch)
        with self.assertRaises(LookupError):clock.to_host(100_000_000)

    def test_pause_and_host_clock_regression(self):
        clock = RosClockBridge()
        clock.observe(100_000_000, 1_000_000_000)
        self.assertTrue(clock.observe(200_000_000, 3_000_000_000))
        with self.assertRaises(LookupError):clock.to_host(150_000_000)
        with self.assertRaises(ValueError):clock.observe(300_000_000, 2_000_000_000)


if __name__ == "__main__":
    unittest.main()
