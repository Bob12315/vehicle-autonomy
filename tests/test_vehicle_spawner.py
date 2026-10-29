"""World-independent vehicle source and pure instance assembly contracts."""
import json
from pathlib import Path
import socket
import tempfile
import unittest
import xml.etree.ElementTree as ET

from vehicle_autonomy.app.simulation.spawner import PortLease, bind_model, instance_ports
from vehicle_autonomy.app.simulation.vehicles import VehicleRegistry


MODEL = '''<sdf version="1.9"><model name="fixture"><link name="body">
<pose>0 0 .2 0 0 0</pose><inertial><mass>2</mass><inertia><ixx>.1</ixx><iyy>.2</iyy><izz>.3</izz></inertia></inertial>
<sensor name="imu" type="imu"><pose degrees="true">0 .1 .2 180 0 0</pose><imu><angular_velocity><x><noise type="gaussian"><stddev>.01</stddev></noise></x></angular_velocity></imu></sensor>
</link><include><uri>model://camera</uri><name>gimbal</name><pose>0 0 .4 .1 .2 .3</pose></include>
<plugin name="ArduPilotPlugin" filename="ArduPilotPlugin"><fdm_addr>127.0.0.1</fdm_addr><fdm_port_in>9002</fdm_port_in>
<control channel="0"><jointName>wheel</jointName><multiplier>10</multiplier><p_gain>1</p_gain><cmd_topic>/gimbal/cmd</cmd_topic></control></plugin>
<plugin name="Controller" filename="system"><topic>/gimbal/cmd</topic></plugin>
</model></sdf>'''
CAMERA = '''<sdf version="1.9"><model name="camera"><pose>0 0 .1 0 0 0</pose><link name="camera_link"><pose>0 .1 0 0 0 0</pose>
<visual name="mesh"><geometry><mesh><uri>model://camera/meshes/box.dae</uri></mesh></geometry></visual>
<sensor name="camera" type="camera"><pose>0 0 .02 .3 0 0</pose><camera><horizontal_fov>1.57</horizontal_fov></camera></sensor></link></model></sdf>'''


class VehicleSpawnerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root, self.ap, self.plugin, self.twin = [base / p for p in ('repo', 'ap', 'plugin', 'twin')]
        self.catalog = {'schema_version': 1, 'vehicles': {}}
        self.write(self.root / 'simulation/models/fixture/model.sdf', MODEL)
        self.write(self.plugin / 'models/camera/model.sdf', CAMERA)
        self.write(self.plugin / 'models/camera/meshes/box.dae', '<COLLADA/>')
        for owner, path in [(self.ap,'build/sitl/bin/ardurover'), (self.ap,'defaults.parm'),
                            (self.plugin,'build/libArduPilotPlugin.so'), (self.plugin,'src/ArduPilotPlugin.cc'),
                            (self.plugin,'CMakeLists.txt'), (self.root,'simulation/profiles/rover.toml')]:
            self.write(owner / path, 'fixed input\n')
        (self.ap / 'build/sitl/bin/ardurover').chmod(0o700)
        self.catalog['vehicles']['rover'] = {'version': 'test-1', 'model_name': 'fixture',
            'model_path': 'root:simulation/models/fixture/model.sdf',
            'profile_path': 'root:simulation/profiles/rover.toml',
            'binary': 'ardupilot:build/sitl/bin/ardurover', 'parameters': ['ardupilot:defaults.parm'],
            'clearance_z': 0, 'radius': .72, 'height': .5, 'locks': {}}
        self.catalog['vehicles']['vtol'] = {'version': 'blocked-1', 'model_name': None,
            'model_path': None, 'profile_path': None, 'binary': None, 'parameters': [],
            'reason': 'Dedicated VTOL Framework profile unavailable'}
        self.save_catalog()
        self.catalog['vehicles']['rover']['locks'] = self.registry().get('rover')['source_files']
        self.save_catalog()

    @staticmethod
    def write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def save_catalog(self):
        self.write(self.root / 'simulation/vehicles/catalog.json', json.dumps(self.catalog))

    def registry(self):
        return VehicleRegistry(self.root, ardupilot_root=self.ap, plugin_root=self.plugin, twin_root=self.twin)

    def test_ready_is_json_source_inventory_including_nested_sensor_extrinsics(self):
        result = self.registry().get('rover')
        self.assertEqual(result['status'], 'READY', result['reason'])
        json.dumps(self.registry().list_vehicles())
        self.assertEqual(len(result['sensors']), 2)
        camera = result['sensors'][1]
        self.assertEqual(camera['parent_link'], 'camera_link')
        self.assertEqual(camera['sensor_pose']['value'], '0 0 .02 .3 0 0')
        self.assertEqual(camera['include_chain'][0]['pose']['value'], '0 0 .4 .1 .2 .3')
        self.assertIn('<mass>2</mass>', result['physics']['links'][0]['inertial'])
        self.assertEqual(result['actuators'][0]['channel'], '0')

    def test_owned_instances_share_immutable_model_and_parameter_hashes(self):
        registry = self.registry()
        before = (self.root / 'simulation/models/fixture/model.sdf').read_bytes()
        outputs = [registry.prepare('rover', Path(self.temp.name) / f'world-{i}',
                    entity_name=f'rover_{i}', instance=i, system_id=i + 1) for i in (40, 41)]
        for key in ('version', 'fingerprint', 'model_hash', 'sensor_hash', 'parameters_hash'):
            self.assertEqual(outputs[0][key], outputs[1][key])
        self.assertNotEqual(outputs[0]['fdm_port'], outputs[1]['fdm_port'])
        self.assertEqual(before, (self.root / 'simulation/models/fixture/model.sdf').read_bytes())
        for output in outputs:
            self.assertEqual(output['parameters'][0].read_bytes(), (self.ap / 'defaults.parm').read_bytes())
            self.assertEqual(output['profile_path'].read_bytes(), (self.root / 'simulation/profiles/rover.toml').read_bytes())
            source = ET.fromstring(MODEL).find('model')
            owned = ET.parse(output['model_path']).getroot().find('model')
            self.assertEqual(ET.tostring(source.find('link')), ET.tostring(owned.find('link')))
            self.assertEqual(owned.find('.//p_gain').text, '1')
            self.assertEqual(owned.find('.//cmd_topic').text, f"/{output['entity_name']}/gimbal/cmd")
            self.assertEqual(owned.find('.//topic').text, owned.find('.//cmd_topic').text)
            mesh = output['resource_paths'][0] / 'camera/meshes/box.dae'
            self.assertTrue(mesh.is_file())
            camera_tree = ET.parse(output['resource_paths'][0] / 'camera/model.sdf')
            self.assertEqual(camera_tree.find('.//mesh/uri').text, str(mesh))
            self.assertFalse((output['model_path'].parent / 'world.sdf').exists())
        outputs[0]['parameters'][0].write_text('instance-only')
        self.assertEqual(outputs[1]['parameters'][0].read_text(), 'fixed input\n')
        self.assertEqual((self.ap / 'defaults.parm').read_text(), 'fixed input\n')

    def test_recursive_mesh_change_fails_source_lock(self):
        registry = self.registry()
        before = registry.get('rover')['model_hash']
        (self.plugin / 'models/camera/meshes/box.dae').write_text('changed mesh')
        current = registry.get('rover')
        self.assertEqual(current['status'], 'BLOCKED')
        self.assertIn('source lock mismatch', current['reason'])
        self.assertNotEqual(current['model_hash'], before)
        with self.assertRaises(ValueError):
            registry.prepare('rover', Path(self.temp.name) / 'blocked', entity_name='vehicle', instance=40, system_id=41)

    def test_source_parameter_change_and_missing_binary_fail_closed(self):
        (self.ap / 'defaults.parm').write_text('changed')
        self.assertEqual(self.registry().get('rover')['status'], 'BLOCKED')
        (self.ap / 'build/sitl/bin/ardurover').unlink()
        self.assertEqual(self.registry().get('rover')['status'], 'BLOCKED')

    def test_vtol_and_unknown_kind_cannot_prepare(self):
        self.assertEqual(self.registry().get('vtol')['status'], 'BLOCKED')
        with self.assertRaises(ValueError):
            self.registry().prepare('vtol', Path(self.temp.name) / 'vtol', entity_name='vtol', instance=40, system_id=41)
        for kind in ('hardware_controlled', 'hardware_readonly', 'quadplane', None):
            with self.assertRaises(ValueError):
                self.registry().get(kind)

    def test_reused_directory_and_source_output_rejected(self):
        registry = self.registry()
        with self.assertRaises(ValueError):
            registry.prepare('rover', self.plugin / 'new-output', entity_name='rover', instance=40, system_id=41)
        output = Path(self.temp.name) / 'owned'
        registry.prepare('rover', output, entity_name='rover', instance=40, system_id=41)
        with self.assertRaises(ValueError):
            registry.prepare('rover', output, entity_name='rover', instance=40, system_id=41)

    def test_instance_identity_rejects_hardware_and_invalid_transport(self):
        source = self.root / 'simulation/models/fixture/model.sdf'
        for name, instance, system in [('127.0.0.1:5760', 40, 41), ('vehicle', 0, 1),
                                       ('vehicle', 101, 102), ('vehicle', True, 2), ('vehicle', 40, 1)]:
            with self.assertRaises(ValueError):
                bind_model(source, Path(self.temp.name) / 'invalid.sdf', entity_name=name,
                           instance=instance, system_id=system)
        self.assertFalse((Path(self.temp.name) / 'invalid.sdf').exists())

    def test_port_leases_lock_allocation_and_auxiliary_port_occupant(self):
        locks = Path(self.temp.name) / 'locks'
        with PortLease.acquire(locks, minimum=90, maximum=92) as first:
            with PortLease.acquire(locks, minimum=90, maximum=92) as second:
                self.assertNotEqual(first.instance, second.instance)
                self.assertEqual(first.system_id, first.instance + 1)
        # Auxiliary UART listener must also block this instance, even if the
        # main MAVLink/FDM ports are free.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(('127.0.0.1', instance_ports(93)['tcp_aux'][0]))
            with self.assertRaises(RuntimeError):
                PortLease.acquire(locks, minimum=93, maximum=93)
        with PortLease.acquire(locks, minimum=93, maximum=93) as lease:
            self.assertEqual(lease.tcp_port, 6690)
            self.assertEqual(lease.fdm_port, 9932)
            self.assertEqual(lease.udp_port, 6431)


if __name__ == '__main__':
    unittest.main()
