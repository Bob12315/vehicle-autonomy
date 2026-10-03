"""Environment provenance, validation and snapshot-version binding."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from environments.resources import Environment
from runtime.simulation_profile import SimulationProfile
from world_model import WorldModel, FreshnessLimits
from tests.test_simulation_runtime import Clock


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.path = Path('simulation/environments/copter.toml')
        self.environment = Environment.load(self.path)
        self.profile = SimulationProfile.load('simulation/profiles/copter.toml')

    def test_explicit_home_reference_and_snapshot_dependency(self):
        env = self.environment.check_safety(self.profile.safety).bind('epoch-one')
        self.assertEqual(env.home().position.x, 0)
        self.assertTrue(env.home_source)
        self.assertNotEqual(env.reference, env.bind('epoch-two').reference)
        with self.assertRaises(ValueError):
            self.environment.resolve('A')
        with self.assertRaises(ValueError):
            env.resolve('missing')
        model = WorldModel('epoch-one', FreshnessLimits(1, 1, 1))
        model.update_environment(env.reference)
        world = model.publish(Clock()())
        self.assertEqual(world.environment, env.reference)
        self.assertTrue(any(d.resource_type == 'Environment' and d.version == env.version for d in world.dependencies))
        with self.assertRaises(ValueError):
            env.check_safety(replace(self.profile.safety, max_x_m=4))

    def test_origin_change_is_rejected(self):
        from contracts.core.geometry import GeoPoint
        from contracts.core.stamped import Stamped
        from tests import test_simulation_runtime as helpers
        harness = helpers.SimulationRuntimeTests()
        harness.setUp()
        harness.runtime.connect()
        harness.cycle(harness.heartbeat()+harness.state_messages())
        state = harness.runtime.world_snapshot().vehicle
        with self.assertRaises(ValueError):
            self.environment.validate_origin(state)
        state = replace(state, global_position=Stamped("earth", harness.clock(), self.environment.origin))
        self.environment.validate_origin(state)
        moved = replace(state, global_position=Stamped("earth", harness.clock(),
            GeoPoint(self.environment.origin.latitude_deg+.001, self.environment.origin.longitude_deg, 584)))
        with self.assertRaises(ValueError):
            self.environment.validate_origin(moved)
        harness.runtime.shutdown()

    def test_invalid_resource_data(self):
        raw = self.path.read_text()
        bad = [raw.replace('frame = "odom"', 'frame = "map"', 1),
               raw.replace('name = "A"', 'name = "HOME"'),
               raw.replace('home = "HOME"', 'home = "unknown"'),
               raw.replace('home_source = "explicit training profile home in odom; rebind per session"', 'home_source = ""'),
               raw.replace('position = [2.0, 1.0, 1.5]', 'position = [9.0, 1.0, 1.5]'),
               raw.replace('frame = "odom"\nposition = [2.0', 'frame = "map"\nposition = [2.0')]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'bad.toml'
            for content in bad:
                with self.subTest(content=content[:120]):
                    path.write_text(content)
                    with self.assertRaises(ValueError):
                        Environment.load(path)

    def test_application_detects_hot_change_and_rebinds_reconnect(self):
        from deployment.application_runtime import ApplicationRuntime
        from tests import test_simulation_runtime as helpers
        harness = helpers.SimulationRuntimeTests()
        harness.setUp()
        app = ApplicationRuntime(harness.runtime.profile, profile_name='copter_sim', runtime=harness.runtime)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'scene.toml'
            path.write_bytes(self.path.read_bytes())
            app.environment_path = path
            harness.runtime.connect()
            harness.clock.advance()
            harness.transports[-1].incoming.append(harness.heartbeat()+harness.state_messages())
            app.cycle()
            old = app.environment.reference
            self.assertEqual(harness.runtime.world_snapshot().environment, old)
            harness.transports[-1].disconnected = True
            harness.clock.advance()
            app.cycle()
            harness.clock.advance()
            app.cycle()
            self.assertNotEqual(app.environment.reference, old)
            path.write_text(path.read_text()+'\n# changed\n')
            harness.clock.advance()
            app.cycle()
            self.assertIsNone(app.environment)
            self.assertEqual(app.state, 'DEGRADED')
            self.assertFalse(harness.runtime.authority.system_send)
            app.shutdown()
