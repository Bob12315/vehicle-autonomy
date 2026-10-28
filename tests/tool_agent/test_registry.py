from copy import deepcopy
import os
from pathlib import Path
import tempfile
import socket
import unittest

from vehicle_autonomy.app.tools.builtins import registry
from vehicle_autonomy.app.tools.local import LocalTools
from vehicle_autonomy.app.tools.schema import manifest
from vehicle_autonomy.app.tools.storage import Store
from .helpers import tool, CTX


class RegistryTests(unittest.TestCase):
    def test_nav2_inputs_are_bound_to_vehicle_namespace_not_another_global_robot(self):
        from vehicle_autonomy.app.tools.ros_tools import nav2_parameters
        text=nav2_parameters('odom_topic: /odom\ntopic: /scan\nmap_topic: /map\nuse_sim_time: true\n','/second_vehicle')
        self.assertIn('odom_topic: /second_vehicle/odom',text);self.assertIn('topic: /second_vehicle/scan',text);self.assertIn('map_topic: /second_vehicle/map',text)
        self.assertNotIn(': /odom',text);self.assertNotIn(': /scan',text);self.assertNotIn(': /map',text)
    def test_root_ros_namespace_expands_without_double_slashes(self):
        self.assertEqual(LocalTools._expand(['{namespace}/tf','__ns:={namespace}'],CTX|{'ros_namespace':'/'}),['/tf','__ns:=/'])
    def test_all_standard_manifests_validate_without_optional_imports(self):
        value=registry()
        self.assertEqual({m['id'] for m in value['tools']},{'rviz2','qgroundcontrol','gazebo','nav2','ros2','sitl'})
        for entry in value['tools']:self.assertEqual(manifest(entry),entry)

    def test_absent_dependencies_remain_missing_and_qgc_requires_monitor(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'state')
            try:
                qgc=tool('qgroundcontrol');qgc['permissions']=['desktop']
                local=LocalTools([qgc],store,environment={'DISPLAY':':1','PATH':os.defpath})
                try:
                    self.assertFalse(local.check('qgroundcontrol','default')['launchable'])
                    with self.assertRaisesRegex(ValueError,'telemetry-only'):local.execute('launch','qgroundcontrol','default',CTX)
                finally:local.close()
            finally:store.close()

    def test_tool_registration_requires_no_ui_changes_and_redacts_launch_code(self):
        entry=tool('another-custom-tool');entry['profiles']['default']['env']['PRIVATE']='secret'
        public=LocalTools.public_manifest(manifest(entry))
        self.assertEqual(public['id'],'another-custom-tool')
        self.assertNotIn('env',public['profiles']['default']);self.assertNotIn('argv',public['profiles']['default'])

    def test_busy_simulator_port_is_installed_but_cannot_launch(self):
        with tempfile.TemporaryDirectory() as directory,socket.socket() as external:
            external.bind(('127.0.0.1',0));external.listen()
            entry=tool();entry['profiles']['default']['exclusive_ports']=[dict(protocol='tcp',port=external.getsockname()[1])]
            store=Store(Path(directory)/'state');local=LocalTools([entry],store)
            try:
                check=local.check('fixture','default');self.assertTrue(check['installed']);self.assertFalse(check['launchable'])
                with self.assertRaisesRegex(ValueError,'busy simulation'):local.execute('launch','fixture','default',CTX)
                self.assertEqual(external.getsockname()[0],'127.0.0.1');self.assertFalse(local.instances)
            finally:local.close();store.close()
