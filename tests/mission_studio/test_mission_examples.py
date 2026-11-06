"""Examples compile against real contracts and remain inert until explicit Run."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from vehicle_autonomy.actions.catalog import capabilities, register_standard
from vehicle_autonomy.app.mission_designer.mission_examples import examples
from vehicle_autonomy.app.mission_designer.studio_service import StudioService
from vehicle_autonomy.contracts.action import ActionContext
from vehicle_autonomy.contracts.core.primitives import ResourceVersion, SchemaVersion
from vehicle_autonomy.contracts.world.models import WorldSnapshot
from vehicle_autonomy.engine.action.registry import ActionRegistry
from vehicle_autonomy.engine.mission.graph import validate
from tests.action_system.test_runtime import Driver
from tests.mission_graph import test_graph as graph_tests


class MissionExampleTests(unittest.TestCase):
    def driver(self, kind='rover', *, owned=True):
        driver = Driver()
        driver.context = lambda: ActionContext('v', kind, capabilities(kind), owned)
        return driver

    def registry(self):
        registry = ActionRegistry()
        register_standard(registry)
        return registry

    def test_examples_compile_with_pinned_actions_and_reject_wrong_vehicle(self):
        registry = self.registry()
        for kind in ('rover', 'copter', 'plane'):
            driver = self.driver(kind)
            for definition in examples('v', kind):
                with self.subTest(kind=kind, mission=definition['mission_id']):
                    compiled = validate(definition, registry, {'v': driver}).to_dict()
                    self.assertTrue(all(n['action_version'] == '1.0.0' for n in compiled['nodes'] if n['type'] == 'Action'))
            self.assertFalse(driver.writes)
            self.assertFalse(driver.opened)
        patrol = next(d for d in examples('v', 'rover') if d['mission_id'] == 'Example_Ground_Patrol')
        with self.assertRaises(ValueError):
            validate(patrol, registry, {'v': self.driver('copter')})

    def execute_readonly(self, identifier):
        harness = graph_tests.GraphTests()
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        register_standard(harness.registry)
        harness.driver.context = self.driver().context
        harness.driver.snapshot = lambda: WorldSnapshot(SchemaVersion(1, 0), 'example', ResourceVersion('example', 1), harness.clock())
        definition = next(d for d in examples('v', 'rover') if d['mission_id'] == identifier)
        run = harness.engine.start(definition, allow_send=False)
        harness.ticks(180)
        view = harness.engine.view(run['id'])
        self.assertFalse(harness.driver.writes)
        self.assertFalse(harness.driver.opened)
        return view

    def test_sampling_loop_produces_three_results_without_write_authority(self):
        view = self.execute_readonly('Example_StateSurvey')
        self.assertEqual(view['state'], 'SUCCEEDED', view['error'])
        values = {v['name']: v['data']['value'] for v in view['studio']['blackboard']['values'] if v['scope_id'] == 'mission'}
        self.assertEqual(values['read_only_flags'], [True, True, True])
        self.assertEqual(values['vehicle_kinds'], ['rover', 'rover', 'rover'])

    def test_missing_vehicle_state_takes_unknown_branch_without_motion(self):
        view = self.execute_readonly('Example_DisarmedBranch')
        self.assertEqual(view['state'], 'UNKNOWN')

    def test_late_vehicle_attachment_installs_templates_once_without_overwrite(self):
        registry = self.registry()
        service = SimpleNamespace(drivers={}, registry=registry, studio_demo=False,
                                  missions=SimpleNamespace(views=lambda: []),
                                  journal=SimpleNamespace(data={'versions': {}}))
        with tempfile.TemporaryDirectory() as folder:
            studio = StudioService(service, Path(folder)/'library')
            self.addCleanup(studio.close)
            self.assertFalse(studio.library.snapshot()['templates'])
            driver = self.driver()
            service.drivers['v'] = driver
            data = studio.handle('studio-b.library', {})
            template = data['templates']['Example_Ground_Patrol']
            changed = template['definition']
            changed['name'] = '保留用户的模板修改'
            studio.library.template('Example_Ground_Patrol', changed, expected_hash=template['definition_hash'])
            again = studio.handle('studio-b.library', {})
            self.assertEqual(again['templates']['Example_Ground_Patrol']['definition']['name'], changed['name'])
            self.assertEqual(set(data['templates']), set(again['templates']))
            self.assertFalse(again['drafts'])
            self.assertFalse(again['publications'])
            self.assertFalse(driver.writes)
            self.assertFalse(driver.opened)
            del service.drivers['v']
            self.assertEqual(set(studio.handle('studio-b.library', {})['templates']), set(again['templates']))

    def test_hardware_context_does_not_install_simulation_templates(self):
        service = SimpleNamespace(drivers={'v': self.driver(owned=False)}, registry=self.registry(), studio_demo=False)
        with tempfile.TemporaryDirectory() as folder:
            studio = StudioService(service, Path(folder)/'library')
            try:
                self.assertFalse(studio.library.snapshot()['templates'])
            finally:
                studio.close()

    def test_new_rescue_template_preserves_old_templates_and_user_drafts(self):
        from vehicle_autonomy.app.scenarios.cuadc.rescue import template
        service=SimpleNamespace(drivers={},registry=self.registry(),studio_demo=False)
        with tempfile.TemporaryDirectory() as folder:
            studio=StudioService(service,Path(folder)/'library');self.addCleanup(studio.close)
            old=template();old['version']='1.0.0';old['name']='保留旧模板'
            saved=studio.library.template('Rescue_2026_FullAuto',old)
            draft=studio.library.save(old,0)
            service.drivers['v']=self.driver('copter');studio.install_examples()
            data=studio.library.snapshot()
            self.assertEqual(data['templates']['Rescue_2026_FullAuto'],saved)
            self.assertEqual(data['drafts'][old['mission_id']],draft)
            self.assertEqual(data['templates']['Rescue_2026_FullAuto@1.1.0']['definition']['version'],'1.1.0')
