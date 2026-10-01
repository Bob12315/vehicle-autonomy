"""Target chassis topology and ArduPilot servo bindings."""

from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


MODEL = Path(__file__).resolve().parents[1] / "simulation/models/target_rover/model.sdf"


class RoverModelTests(unittest.TestCase):
    def test_exact_two_drives_and_two_passive_rear_casters(self):
        root = ET.parse(MODEL).getroot()
        model = root.find("model")
        joints = {joint.attrib["name"]: joint for joint in model.findall("joint")}
        self.assertEqual(set(joints), {
            "front_left_drive_joint", "front_right_drive_joint",
            "rear_left_swivel_joint", "rear_left_roll_joint",
            "rear_right_swivel_joint", "rear_right_roll_joint",
        })
        links = {link.attrib["name"] for link in model.findall("link")}
        self.assertEqual(links, {"base_link", "front_left_wheel", "front_right_wheel",
                                 "rear_left_swivel", "rear_left_caster_wheel",
                                 "rear_right_swivel", "rear_right_caster_wheel"})
        for side in ("left", "right"):
            self.assertEqual(joints[f"rear_{side}_swivel_joint"].findtext("axis/xyz"), "0 0 1")
            self.assertEqual(joints[f"rear_{side}_roll_joint"].findtext("axis/xyz"), "0 1 0")
            self.assertEqual(joints[f"rear_{side}_swivel_joint"].findtext("axis/limit/effort"), "0")
            self.assertEqual(joints[f"rear_{side}_roll_joint"].findtext("axis/limit/effort"), "0")
        plugin = next(p for p in model.findall("plugin") if p.attrib.get("name") == "ArduPilotPlugin")
        controls = [(p.attrib["channel"], p.findtext("jointName")) for p in plugin.findall("control")]
        self.assertEqual(controls, [("0", "front_left_drive_joint"),
                                    ("2", "front_right_drive_joint")])
        self.assertEqual(plugin.findtext("fdm_port_in"), "9002")
        self.assertEqual(plugin.findtext("imuName"), "imu_sensor")
        powered = {p.findtext("joint_name") for p in model.findall("plugin")
                   if p.attrib.get("name") == "gz::sim::systems::ApplyJointForce"}
        self.assertEqual(powered, {"front_left_drive_joint", "front_right_drive_joint"})


if __name__ == "__main__":
    unittest.main()
