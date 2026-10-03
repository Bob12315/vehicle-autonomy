import math
import unittest
from actions.basic import BasicParameters, register_basic
from applications.basic_catalog import build, capabilities
from environments.resources import Environment
from contracts.vehicle.ports import VehicleCapabilities
from core.action_registry import ActionRegistry
from core.mission import MissionValidator
from core.sitl_mode_action import SITL_MODE_SPEC, SitlModeAction
from pathlib import Path

class BasicMissionTests(unittest.TestCase):
    def test_compiled_named_routes_and_capabilities(self):
        registry=ActionRegistry();register_basic(registry);registry.register_typed(SITL_MODE_SPEC,SitlModeAction())
        for kind in ('copter','rover'):
            env=Environment.load(Path(f'simulation/environments/{kind}.toml')).bind('session1')
            plan=build('basic_route',kind,env,4 if kind=='copter' else 15)
            compiled=MissionValidator(registry).compile(plan,VehicleCapabilities(capabilities(kind)))
            self.assertIn('goto_b',[s.step.step_id for s in compiled.steps])
            for step in compiled.steps:
                self.assertEqual(step.step.max_attempts,1)
                self.assertEqual(step.step.on_failure.value,'STOP')
                if step.step.action.startswith('basic.'):
                    self.assertEqual(step.step.parameters.environment,env.reference)
            if kind=='copter':
                with self.assertRaises(ValueError):MissionValidator(registry).compile(plan,VehicleCapabilities(capabilities('rover')))
    def test_preflight_bad_values(self):
        env=Environment.load(Path('simulation/environments/copter.toml')).bind('s')
        for kw in ({'height_m':math.nan},{'timeout_ns':0},{'timeout_ns':True},{'duration_ns':50_000_000_000}):
            with self.assertRaises(ValueError):BasicParameters('copter',env.reference,**kw)
        with self.assertRaises(ValueError):build('unknown','copter',env,4)
        with self.assertRaises(ValueError):BasicParameters('copter',env.reference,env.bind('other').resolve('A'))
