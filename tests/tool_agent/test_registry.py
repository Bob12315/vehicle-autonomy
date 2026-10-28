from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest

from vehicle_autonomy.app.tools.builtins import registry
from vehicle_autonomy.app.tools.local import LocalTools
from vehicle_autonomy.app.tools.schema import manifest
from vehicle_autonomy.app.tools.storage import Store
from .helpers import tool, CTX


class RegistryTests(unittest.TestCase):
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
