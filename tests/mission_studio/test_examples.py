from dataclasses import replace
import unittest
from tests.mission_graph import test_graph as legacy
from vehicle_autonomy.contracts.action import ActionContext
from vehicle_autonomy.engine.mission.graph import validate
from vehicle_autonomy.actions.simulation.studio_demo import register_demo,Selection,Target,DemoInstance
from vehicle_autonomy.app.mission_designer.studio_examples import cuadc


class ExampleTests(unittest.TestCase):
    def setUp(self):
        self.h=legacy.GraphTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.h.driver.context=lambda:ActionContext('v','copter',frozenset(),True)
        register_demo(self.h.registry)
    def execute(self,loss=False):
        child,parent=cuadc('v',target_loss=loss);spec=validate(parent,self.h.registry,{'v':self.h.driver},resolve=lambda *_:child)
        i=self.h.engine.start(spec)['id'];self.h.ticks(80,step=.01);v=self.h.engine.view(i)
        self.assertEqual(v['state'],'SUCCEEDED',v['error']);self.assertTrue(v['release_safe']);self.assertEqual(self.h.driver.writes,[])
        return v,{c['name']:c['data']['value'] for c in v['studio']['blackboard']['values'] if c['scope_id']=='mission'}
    def test_two_smallest_physical_targets_have_distinct_scopes_and_results(self):
        v,board=self.execute();self.assertEqual(len(board['detections']),3);self.assertEqual([t['id'] for t in board['selected_targets']],['T-02','T-03'])
        self.assertEqual([r['target_id'] for r in board['results']],['T-02','T-03']);self.assertEqual(board['simulated_payload_remaining'],0)
        self.assertTrue(all(r['simulation'] and not r['physical_action_confirmed'] for r in board['results']))
        scopes=[s for s in v['studio']['blackboard']['scopes'] if s['kind']=='submission'];self.assertEqual(len(scopes),2)
        self.assertEqual(board['mission_status'],'SOFTWARE_SIMULATION_COMPLETE')
    def test_lost_target_recovers_without_overwriting_second_iteration_or_inventory(self):
        v,board=self.execute(True);self.assertEqual([r['status'] for r in board['results']],['RECOVERED_TARGET_LOST','SIMULATED_OPERATION_COMPLETE'])
        self.assertEqual(board['simulated_payload_remaining'],1)
        self.assertTrue(any(e['state']=='FAILED' and e['node_id']=='confirm' for e in v['studio']['executions']))
    def test_untrusted_size_and_pixel_area_do_not_select_targets(self):
        detections=tuple(Target(i,size,source,pixels,True,False) for i,size,source,pixels in [('bad',.01,'bbox_pixel_area',1),('physical-small',.2,'declared_software_scene_geometry',1000),('physical-large',.5,'declared_software_scene_geometry',10)])
        result=DemoInstance('SelectTargets',Selection(detections)).tick(None).result
        self.assertEqual([t['id'] for t in result['selected_targets']],['physical-small','physical-large'])
    def test_demo_rejects_hardware_context_even_with_no_effects(self):
        f=self.h.registry.resolve_typed('Sim.PreflightCheck').factory
        with self.assertRaises(ValueError):f.validate_context(None,None,ActionContext('v','copter',frozenset(),False))
