"""Truth parsing and freshness failures must be explicit."""

import unittest
from unittest.mock import patch

from gz.msgs10.pose_v_pb2 import Pose_V

from tests.simulation.oracle import GazeboTruthOracle


def pose_message(sec: int, *, model: str = "iris", x: float = 0.0, z: float = 0.0) -> Pose_V:
    message = Pose_V()
    message.header.stamp.sec = sec
    pose = message.pose.add()
    pose.name = model
    pose.position.x = x
    pose.position.z = z
    pose.orientation.w = 1.0
    return message


class GazeboOracleTests(unittest.TestCase):
    def make_oracle(self):
        with patch("tests.simulation.oracle.Node") as node:
            node.return_value.subscribe.return_value = True
            oracle = GazeboTruthOracle("runway", "iris")
        self.assertEqual(oracle.topic, "/world/runway/pose/info")
        return oracle

    def test_new_model_pose_and_simulation_speed(self):
        oracle = self.make_oracle()
        oracle._ingest(pose_message(1, x=0, z=0))
        oracle._ingest(pose_message(2, x=1, z=2))
        self.assertEqual(oracle.wait_new(after_host_ns=0, timeout_s=.01).x_m, 1)
        self.assertAlmostEqual(oracle.recent_speed_mps(window_sim_s=.5), 1.0)
        self.assertAlmostEqual(oracle.recent_vertical_speed_mps(window_sim_s=.5), 2.0)
        self.assertEqual(oracle.recent_velocity_enu(window_sim_s=.5), (1.0, 0.0, 2.0))
        self.assertAlmostEqual(oracle.recent_yaw_rate_rad_s(window_sim_s=.5), 0.0)

    def test_missing_model_and_clock_regression_fail(self):
        oracle = self.make_oracle()
        oracle._ingest(pose_message(1, model="other"))
        with self.assertRaisesRegex(RuntimeError, "model iris missing"):
            oracle.latest()
        oracle = self.make_oracle()
        oracle._ingest(pose_message(2))
        oracle._ingest(pose_message(1))
        with self.assertRaisesRegex(RuntimeError, "time regressed"):
            oracle.latest()


if __name__ == "__main__":
    unittest.main()
