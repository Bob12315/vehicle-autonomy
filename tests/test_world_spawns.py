"""Static spawn admission is independent of native movement acceptance."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from vehicle_autonomy.app.simulation.catalog import SceneRegistry
from vehicle_autonomy.app.simulation.scenarios import box
from vehicle_autonomy.app.simulation.world_spawns import WorldSpawnRegistry


DEFINITIONS = {
    'rover': {'id': 'rover-standard', 'family': 'rover', 'radius': .72, 'clearance_z': 0., 'height': .5},
    'copter': {'id': 'iris-standard', 'family': 'copter', 'radius': .65, 'clearance_z': .195, 'height': .5},
    'plane': {'id': 'plane-standard', 'family': 'plane', 'radius': 1.5, 'clearance_z': .22, 'height': .65},
    'vtol': {'id': 'vtol-unqualified', 'family': 'vtol', 'radius': 1.5, 'clearance_z': .22, 'height': .65},
}


class WorldSpawnTests(unittest.TestCase):
    def setUp(self):
        self.scenes = SceneRegistry()
        self.registry = WorldSpawnRegistry(self.scenes)

    def test_priority_ground_pairings_use_fixed_vehicle_clearance(self):
        original = deepcopy(DEFINITIONS)
        for family, scenes in [('rover', ['R01', 'R04', 'R06', 'R03']),
                               ('copter', ['C01', 'C02', 'C04', 'C05']),
                               ('plane', ['F01', 'F02', 'F03'])]:
            for scene_id in scenes:
                with self.subTest(scene=scene_id, family=family):
                    result = self.registry.validate(scene_id, DEFINITIONS[family], seed=42)
                    self.assertEqual({'x', 'y', 'z', 'heading_deg', 'preset_id'}, set(result))
                    ground = .03 if scene_id in ('R03', 'C04') else .042 if scene_id.startswith('F') else 0.
                    self.assertAlmostEqual(ground+DEFINITIONS[family]['clearance_z'], result['z'])
                    self.assertEqual('center', result['preset_id'])
        self.assertEqual(original, DEFINITIONS)

    def test_description_exposes_actual_world_geography_and_copies(self):
        description = self.registry.describe('R01')
        self.assertEqual([120, 120], description['extent_m'])
        self.assertEqual(-35.363262, description['geographic_reference']['latitude_deg'])
        self.assertEqual(149.165237, description['geographic_reference']['longitude_deg'])
        self.assertEqual(584, description['geographic_reference']['elevation'])
        self.assertTrue(description['vehicle_support']['rover']['available'])
        self.assertTrue(description['constraints']['admission_only'])
        description['spawn_presets'][0]['x'] = 999
        description['constraints']['regions'][0]['bounds'][0] = -999
        self.assertEqual(0, self.registry.describe('R01')['spawn_presets'][0]['x'])
        self.assertEqual(-4, self.registry.describe('R01')['constraints']['regions'][0]['bounds'][0])

    def test_lio_loop_fixture_rejects_column_spawn_and_preserves_original_scene(self):
        for family in ('rover','copter'):
            self.assertEqual(0.,self.registry.validate('L02',DEFINITIONS[family],{'id':'center'})['x'])
            with self.assertRaises(ValueError):
                self.registry.validate('L02',DEFINITIONS[family],dict(x=2.,y=0.,z=DEFINITIONS[family]['clearance_z'],heading_deg=0.))
        with tempfile.TemporaryDirectory() as tmp:
            original=ET.parse(self.scenes.generate('L01',Path(tmp)/'original.sdf'))
            loop=ET.parse(self.scenes.generate('L02',Path(tmp)/'loop.sdf'))
            self.assertIsNone(original.find(".//model[@name='lidar_inner_column']"))
            column=loop.find(".//model[@name='lidar_inner_column']")
            self.assertIsNotNone(column.find('.//collision/geometry/cylinder'))
            self.assertEqual('2 0 1 0 0 0',column.findtext('pose'))

    def test_cross_family_world_does_not_select_or_modify_vehicle(self):
        result = self.registry.validate('R04', DEFINITIONS['copter'])
        self.assertEqual(.195, result['z'])
        self.assertTrue(self.registry.describe('C01')['vehicle_support']['rover']['available'])
        with self.assertRaisesRegex(ValueError, 'runway'):
            self.registry.validate('C01', DEFINITIONS['plane'])
        with self.assertRaisesRegex(ValueError, 'VTOL'):
            self.registry.validate('F07', DEFINITIONS['vtol'])

    def test_multi_vehicle_separation_uses_both_fixed_radii(self):
        first = self.registry.validate('R01', DEFINITIONS['rover'])
        peer = {'spawn': first, 'definition': DEFINITIONS['rover']}
        for family in ('rover', 'copter'):
            second = self.registry.validate('R01', DEFINITIONS[family], {'id': 'north'}, peers=[peer])
            self.assertEqual(3., second['y'])
            with self.assertRaisesRegex(ValueError, 'separation'):
                self.registry.validate('R01', DEFINITIONS[family], peers=[peer])
        plane = self.registry.validate('F01', DEFINITIONS['plane'])
        peer = {'spawn': plane, 'definition': DEFINITIONS['plane']}
        with self.assertRaisesRegex(ValueError, 'separation'):
            self.registry.validate('F01', DEFINITIONS['plane'], {'id': 'north'}, peers=[peer])
        self.assertEqual(6., self.registry.validate('F01', DEFINITIONS['plane'], {'id': 'north-far'}, peers=[peer])['y'])

    def test_plane_corridor_accounts_for_custom_heading_and_lateral_spawn(self):
        # A small heading offset accumulates lateral drift across 300 m.
        self.registry.validate('F01',DEFINITIONS['plane'],
            dict(x=0,y=0,z=.262,heading_deg=1))
        with self.assertRaisesRegex(ValueError,'runway'):
            self.registry.validate('F01',DEFINITIONS['plane'],
                dict(x=0,y=6,z=.262,heading_deg=2))

    def test_strict_custom_spawn_input_and_ground_height(self):
        for spawn in ({}, {'id': 'center', 'z': 2}, {'id': '../center'}, {'x': 0, 'y': 0},
                      {'x': 0, 'y': 0, 'z': 0, 'heading_deg': 0, 'model': '/tmp/evil'}, [],
                      {'x': True, 'y': 0, 'z': 0, 'heading_deg': 0},
                      {'x': 0, 'y': 0, 'z': float('nan'), 'heading_deg': 0}):
            with self.subTest(spawn=spawn), self.assertRaises(ValueError):
                self.registry.validate('R01', DEFINITIONS['rover'], spawn)
        for family in ('rover', 'copter'):
            definition = DEFINITIONS[family]
            custom = {'x': 1, 'y': 1, 'z': definition['clearance_z'], 'heading_deg': -450}
            result = self.registry.validate('R01', definition, custom)
            self.assertEqual(270, result['heading_deg'])
            self.assertIsNone(result['preset_id'])
            for changes in ({'z': 10}, {'z': -1}, {'x': 4}, {'y': 9}, {'x': 500}):
                with self.subTest(family=family, change=changes), self.assertRaises(ValueError):
                    self.registry.validate('R01', definition, dict(custom, **changes))
        with self.assertRaisesRegex(ValueError, 'World ground height'):
            self.registry.validate('R03', DEFINITIONS['rover'], {'x': 0, 'y': 0, 'z': 0, 'heading_deg': 0})

    def test_plane_heading_and_forward_runway_obstacles(self):
        with self.assertRaisesRegex(ValueError, 'heading'):
            self.registry.validate('F01', DEFINITIONS['plane'], {'x': 0, 'y': 0, 'z': .262, 'heading_deg': 90})
        for scene_id in ('F05', 'F07'):
            self.assertFalse(self.registry.describe(scene_id)['vehicle_support']['plane']['available'])
            with self.assertRaisesRegex(ValueError, 'bridge/platform'):
                self.registry.validate(scene_id, DEFINITIONS['plane'])
        # F03 is clear on its centreline, but its actual side ramp reaches the
        # corridor of the north-far candidate. A preset is not unconditional.
        with self.assertRaisesRegex(ValueError, 'forward runway collision'):
            self.registry.validate('F03', DEFINITIONS['plane'], {'id': 'north-far'})

    def test_unreviewed_upstream_and_dynamic_worlds_fail_closed(self):
        for scene_id in ('U_clearpath-warehouse', 'U_clearpath-orchard', 'R05', 'C06'):
            description = self.registry.describe(scene_id)
            self.assertFalse(any(item['available'] for item in description['vehicle_support'].values()))
            self.assertIsNotNone(description['constraints']['blocked_reason'])
            with self.assertRaisesRegex(ValueError, 'BLOCKED'):
                self.registry.validate(scene_id, DEFINITIONS['rover'])

    def _mutated_registry(self, mutate):
        registry = SceneRegistry()
        generate = registry.generate
        def changed(*args, **kwargs):
            path = generate(*args, **kwargs)
            tree = ET.parse(path)
            mutate(tree.find('world'))
            tree.write(path)
            return path
        registry.generate = changed
        return WorldSpawnRegistry(registry)

    def test_actual_static_geometry_detects_new_obstruction_and_ceiling(self):
        registry = self._mutated_registry(lambda world: box(world, 'unexpected-crate', (0,0,.5,0,0,0), (1,1,1)))
        with self.assertRaisesRegex(ValueError, 'unexpected-crate'):
            registry.validate('R01', DEFINITIONS['rover'])
        # A roof above the initial body is allowed; lowering it intersects the
        # vehicle envelope and blocks it. This does not certify flight indoors.
        self.assertIsNotNone(self.registry.validate('C03', DEFINITIONS['copter']))
        registry = self._mutated_registry(lambda world: world.find("model[@name='roof']/pose").__setattr__('text', '0 0 .3 0 0 0'))
        with self.assertRaisesRegex(ValueError, 'roof'):
            registry.validate('C03', DEFINITIONS['copter'])

    def test_rotated_primitive_uses_conservative_world_aabb(self):
        registry = self._mutated_registry(lambda world: box(world, 'tilted-beam', (1.3,0,.5,0,0,1.57079632679), (.1,2,1)))
        with self.assertRaisesRegex(ValueError, 'tilted-beam'):
            registry.validate('R01', DEFINITIONS['rover'])

    def test_unreviewed_mesh_heightmap_ground_and_frames_block(self):
        def mesh(world):
            geometry = world.find("model[@name='cone_8_-5']//collision/geometry")
            geometry.clear()
            ET.SubElement(ET.SubElement(geometry, 'mesh'), 'uri').text = '/tmp/unreviewed.dae'
        def moved_ground(world):
            world.find("model[@name='ground']/pose").text = '0 0 1 0 0 0'
        def frame(world):
            world.find("model[@name='ground']/pose").set('relative_to', 'unreviewed')
        for mutation in (mesh, moved_ground, frame):
            registry = self._mutated_registry(mutation)
            with self.assertRaisesRegex(ValueError, 'BLOCKED'):
                registry.validate('R01', DEFINITIONS['rover'])
            self.assertFalse(registry.describe('R01')['vehicle_support']['rover']['available'])

    def test_parameter_and_vehicle_definitions_cannot_bypass_validation(self):
        for kwargs in ({'seed': True}, {'seed': -1}, {'parameters': {'obstacle_count': -1}},
                       {'parameters': {'wind_speed': float('inf')}}, {'parameters': {'command': 'run'}}):
            with self.assertRaises(ValueError):
                self.registry.validate('R01', DEFINITIONS['rover'], **kwargs)
        for changes in ({'radius': 0}, {'radius': float('nan')}, {'clearance_z': -1}, {'height': True}, {'family': 'helicopter'}):
            with self.assertRaises(ValueError):
                self.registry.validate('R01', dict(DEFINITIONS['rover'], **changes))
        with self.assertRaises(ValueError):
            self.registry.validate('R01', DEFINITIONS['rover'], peers=[{'spawn': {}, 'definition': DEFINITIONS['rover']}])

    def test_reproducible_actual_random_geometry_checks(self):
        for scene_id, family in [('R06', 'rover'), ('C05', 'copter'), ('F03', 'plane')]:
            for seed in (0, 42, 2**32-1):
                result = self.registry.validate(scene_id, DEFINITIONS[family], seed=seed, parameters={'obstacle_count': 40})
                self.assertEqual(0, result['x'])


if __name__ == '__main__':
    unittest.main()
