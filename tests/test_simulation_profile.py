"""Simulation profile must fail closed before a vehicle socket is opened."""

import json
from pathlib import Path
import tempfile
import unittest

from core.control_authority import ControlAuthority
from runtime.simulation_profile import SimulationProfile


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "simulation/profiles"


class SimulationProfileTests(unittest.TestCase):
    def test_two_vehicle_profiles_and_acceptance_limits(self):
        copter = SimulationProfile.load(PROFILES / "copter.toml")
        rover = SimulationProfile.load(PROFILES / "rover.toml")
        scenarios = json.loads((ROOT / "simulation/scenarios/acceptance-v1.json").read_text())
        self.assertEqual(copter.mode_ids["GUIDED"], 4)
        self.assertEqual(rover.mode_ids["GUIDED"], 15)
        self.assertEqual(rover.mode_ids["HOLD"], 4)
        self.assertLessEqual(scenarios["copter"]["takeoff_height_m"], copter.safety.max_takeoff_m)
        self.assertLessEqual(scenarios["rover"]["forward_body_mps"], rover.safety.max_linear_mps)
        self.assertGreater(rover.safety.max_angular_rad_s, scenarios["rover"]["turn_rate_body_rad_s"])
        authority = ControlAuthority()
        self.assertFalse(authority.system_send)
        self.assertFalse(authority.action_send)

    def test_foreign_host_and_mismatched_rover_mode_rejected(self):
        original = (PROFILES / "rover.toml").read_text()
        for changed in (original.replace('host = "127.0.0.1"', 'host = "192.0.2.1"'),
                        original.replace("GUIDED = 15", "GUIDED = 4")):
            with self.subTest(changed=changed != original), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bad.toml"
                path.write_text(changed)
                with self.assertRaises(ValueError):
                    SimulationProfile.load(path)

    def test_extra_frame_or_stale_state_window_rejected(self):
        original = (PROFILES / "copter.toml").read_text()
        for changed in (original.replace('["odom", "base_link"]', '["odom", "base_link", "map"]'),
                        original.replace('max_snapshot_age_ns = 3000000000', 'max_snapshot_age_ns = 100000000')):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bad.toml"
                path.write_text(changed)
                with self.assertRaises(ValueError):
                    SimulationProfile.load(path)


if __name__ == "__main__":
    unittest.main()
