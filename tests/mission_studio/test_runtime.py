from dataclasses import replace
import unittest
from tests.mission_graph import test_graph as legacy
from tests.mission_studio.test_compiler import definition,node,edge
from vehicle_autonomy.engine.mission.graph import validate


class StudioRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.h=legacy.GraphTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        entry=self.h.registry.resolve_typed('ok')
        self.h.registry.register_typed(replace(entry.spec,version='1.0.1',retryable=True,skippable=True,runtime_mutable_parameters=('count',),
            output_schema={'type':'object','properties':{'count':{'type':'integer'}},'required':['count']}),entry.factory)
    def start(self,d,**kw):return self.h.engine.start(d,**kw)['id']
    def test_real_existing_executor_runs_compiled_sequence_and_typed_bindings(self):
        d=definition(blackboard={'value':dict(schema={'type':'integer'},default=3),'result':dict(schema={'type':'integer'},default=0)})
        d['nodes'][1].update(input_bindings={'count':{'ref':'mission.value'}},output_bindings={'count':{'ref':'mission.result'}})
        i=self.start(d);self.h.ticks(40);v=self.h.engine.view(i)
        self.assertEqual(v['state'],'SUCCEEDED',v['error']);self.assertTrue(v['release_safe']);self.assertEqual(len(v['action_ids']),1)
        value=next(c for c in v['studio']['blackboard']['values'] if c['name']=='result');self.assertEqual(value['data']['value'],3)
        self.assertTrue(any(e['inputs'].get('count',{}).get('value')==3 for e in v['studio']['executions']))
    def test_foreach_has_independent_execution_and_output_records(self):
        d=definition(nodes=[node('start','Start'),node('loop','ForEach',execution_policy={'collection':{'ref':'mission.items'},'max_iterations':2}),
            node('work','Action',action_type='ok',input_bindings={'count':{'ref':'loop.current_item'}},output_bindings={'count':{'ref':'mission.results','mode':'append'}}),node('end','End')],
            edges=[edge('start','loop'),edge('loop','work','body'),edge('loop','end')],blackboard={'items':dict(schema={'type':'array','items':{'type':'integer'}},default=[1,2]),'results':dict(schema={'type':'array','items':{'type':'integer'}},default=[])})
        i=self.start(d);self.h.ticks(50);v=self.h.engine.view(i);self.assertEqual(v['state'],'SUCCEEDED',v['error'])
        executions=[e for e in v['studio']['executions'] if e['node_id']=='work']
        self.assertEqual(len(executions),2);self.assertNotEqual(executions[0]['scope_id'],executions[1]['scope_id']);self.assertNotEqual(executions[0]['execution_id'],executions[1]['execution_id'])
        self.assertEqual([e['inputs']['count']['value'] for e in executions],[1,2])
        result=next(c for c in v['studio']['blackboard']['values'] if c['name']=='results');self.assertEqual(result['data']['value'],[1,2])
    def test_submission_pinned_input_output_mapping_uses_child_scope(self):
        child=definition(blackboard={},interface=dict(inputs={'item':dict(schema={'type':'integer'})},outputs={'count':dict(schema={'type':'integer'})}))
        child['mission_id']='child';child['nodes'][1].update(input_bindings={'count':{'ref':'submission.item'}},output_bindings={'count':{'ref':'submission.count'}})
        parent=definition(blackboard={'result':dict(schema={'type':'integer'},default=0)})
        parent['nodes'][1]=node('work','SubMission',sub_mission=dict(mission_id='child',version='1.0.0'),parameters={'item':3},output_bindings={'count':{'ref':'mission.result'}})
        compiled=validate(parent,self.h.registry,{'v':self.h.driver},resolve=lambda *_:child)
        i=self.start(compiled);self.h.ticks(50);v=self.h.engine.view(i);self.assertEqual(v['state'],'SUCCEEDED',v['error'])
        value=next(c for c in v['studio']['blackboard']['values'] if c['scope_id']=='mission' and c['name']=='result');self.assertEqual(value['data']['value'],3)
    def test_wait_condition_rechecks_unknown_instead_of_boolean_coercion(self):
        d=definition();d['nodes'][1]=node('work','Wait',execution_policy={'mode':'condition','expression':dict(op='eq',source='blackboard',path='mission.ready',value=True),'timeout_s':.3})
        d['blackboard']={'ready':dict(schema={'type':'boolean'},default=False)}
        i=self.start(d);self.h.ticks(30);self.assertEqual(self.h.engine.view(i)['state'],'TIMED_OUT')
    def test_breakpoint_step_override_and_resume_preserve_snapshot(self):
        d=definition(execution_policy=dict(timeout_s=30,breakpoints=['work']))
        d['nodes'][1]['execution_policy']={'runtime_overrides':['count'],'skippable':True}
        i=self.start(d,debug=True);self.h.ticks(5);v=self.h.engine.view(i);self.assertEqual(v['state'],'PAUSED');self.assertFalse(v['action_ids'])
        self.h.engine.debug(i,'override',node_id='work',parameters={'count':4});self.h.engine.debug(i,'step');self.h.ticks(20)
        v=self.h.engine.view(i);self.assertEqual(v['state'],'PAUSED');self.assertEqual(len(v['action_ids']),1)
        self.assertEqual(self.h.actions.view(v['action_ids'][0])['parameters']['count'],4)
        self.assertNotIn('count',v['studio']['definition']['nodes'][1]['parameters'])
        self.h.engine.debug(i,'resume');self.h.ticks(5);self.assertEqual(self.h.engine.view(i)['state'],'SUCCEEDED')
    def test_pause_does_not_freeze_running_action_and_cancel_keeps_exit_barrier(self):
        d=definition();d['nodes'][1]['action_type']='stream'
        i=self.start(d);self.h.ticks(5);self.h.engine.debug(i,'pause');self.h.ticks(10)
        v=self.h.engine.view(i);self.assertEqual(v['state'],'PAUSE_REQUESTED');self.assertEqual(self.h.actions.view(v['action_ids'][0])['state'],'RUNNING')
        self.h.engine.cancel(i);self.h.ticks(10);self.assertEqual(self.h.engine.view(i)['state'],'CANCELLED')
    def test_safe_skip_and_override_contracts_are_not_implicit(self):
        d=definition(execution_policy=dict(breakpoints=['work']));i=self.start(d);self.h.ticks(5)
        with self.assertRaises(ValueError):self.h.engine.debug(i,'skip',node_id='work')
        with self.assertRaises(ValueError):self.h.engine.debug(i,'override',node_id='work',parameters={'count':3})
        self.assertFalse(self.h.engine.view(i)['action_ids'])

