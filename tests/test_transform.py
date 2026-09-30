"""Frame graph behavior for static/dynamic SI transforms."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import unittest

from contracts.core.geometry import Pose3, Quaternion, Transform3, Twist3, Vector3
from contracts.core.time import TimePoint
from core.transform import TransformTree


def at(ns: int, domain: str = "clock") -> TimePoint:
    return TimePoint(ns, datetime(2026, 1, 1, tzinfo=timezone.utc), domain)


def yaw90() -> Quaternion:
    return Quaternion(0, 0, math.sqrt(0.5), math.sqrt(0.5))


class TransformTests(unittest.TestCase):
    def test_static_point_vector_pose_twist_and_inverse(self):
        tree = TransformTree(max_interpolation_gap_ns=100)
        tree.set_static("camera", "base_link", Transform3(Vector3(1, 0, 0), yaw90()))
        tree.set_static("base_link", "map", Transform3(Vector3(0, 2, 0), Quaternion(0, 0, 0, 1)))
        point = tree.transform_point(Vector3(1, 0, 0), from_frame="camera", to_frame="map", at_time=at(10))
        self.assertAlmostEqual(point.x, 1)
        self.assertAlmostEqual(point.y, 3)
        self.assertAlmostEqual(point.z, 0)
        vector = tree.transform_vector(Vector3(1, 0, 0), from_frame="camera", to_frame="map", at_time=at(10))
        self.assertAlmostEqual(vector.x, 0)
        self.assertAlmostEqual(vector.y, 1)
        self.assertEqual(tree.transform(Vector3(1, 0, 0), from_frame="camera", to_frame="map", at_time=at(10)), vector)
        original = tree.transform_point(point, from_frame="map", to_frame="camera", at_time=at(10))
        self.assertAlmostEqual(original.x, 1)
        self.assertAlmostEqual(original.y, 0)
        transformed_pose = tree.transform_pose(Pose3(Vector3(1, 0, 0), Quaternion(0, 0, 0, 1)),
                                               from_frame="camera", to_frame="map", at_time=at(10))
        self.assertAlmostEqual(transformed_pose.position.y, 3)
        self.assertAlmostEqual(transformed_pose.orientation.z, yaw90().z)
        transformed_twist = tree.transform_twist(Twist3(Vector3(1, 0, 0), Vector3(0, 0, 1)),
                                                 from_frame="camera", to_frame="base_link", at_time=at(10))
        self.assertAlmostEqual(transformed_twist.linear.x, 0)
        self.assertAlmostEqual(transformed_twist.linear.y, 0)
        self.assertAlmostEqual(transformed_twist.angular.z, 1)

    def test_dynamic_interpolation_exact_sample_and_no_extrapolation(self):
        tree = TransformTree(max_interpolation_gap_ns=20)
        tree.add_dynamic("odom", "base_link", at(10), Transform3(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1)))
        tree.add_dynamic("odom", "base_link", at(20), Transform3(Vector3(10, 0, 0), yaw90()))
        at_middle = tree.transform_point(Vector3(0, 0, 0), from_frame="odom", to_frame="base_link", at_time=at(15))
        self.assertAlmostEqual(at_middle.x, 5)
        quarter = tree.transform_vector(Vector3(1, 0, 0), from_frame="odom", to_frame="base_link", at_time=at(15))
        self.assertAlmostEqual(quarter.x, math.sqrt(0.5), places=6)
        self.assertAlmostEqual(quarter.y, math.sqrt(0.5), places=6)
        self.assertEqual(tree.resolve("odom", "base_link", at(20)).translation.x, 10)
        with self.assertRaises(LookupError):
            tree.resolve("odom", "base_link", at(21))
        with self.assertRaises(LookupError):
            tree.resolve("odom", "base_link", at(9))
        with self.assertRaises(ValueError):
            tree.resolve("odom", "base_link", at(15, "other"))

    def test_missing_cycle_gap_and_time_regression_fail(self):
        tree = TransformTree(max_interpolation_gap_ns=5)
        with self.assertRaises(LookupError):
            tree.resolve("map", "base_link", at(1))
        tree.set_static("map", "odom", Transform3(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1)))
        tree.add_dynamic("odom", "base_link", at(10), Transform3(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1)))
        tree.add_dynamic("odom", "base_link", at(20), Transform3(Vector3(1, 0, 0), Quaternion(0, 0, 0, 1)))
        with self.assertRaises(LookupError):
            tree.resolve("map", "base_link", at(15))
        with self.assertRaises(ValueError):
            tree.set_static("map", "base_link", Transform3(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1)))
        with self.assertRaises(ValueError):
            tree.add_dynamic("odom", "base_link", at(19), Transform3(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1)))
        with self.assertRaises(ValueError):
            tree.add_dynamic("odom", "base_link", at(30, "other"), Transform3(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1)))
        with self.assertRaises(ValueError):
            tree.set_static("same", "same", Transform3(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1)))
        with self.assertRaises(ValueError):
            TransformTree(max_interpolation_gap_ns=0)


if __name__ == "__main__":
    unittest.main()
