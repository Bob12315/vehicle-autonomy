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
    def test_declared_plan_validity_survives_wait_without_retiming_default_facts(self):
        from tests.action_system.test_runtime import Parameters,Factory
        from vehicle_autonomy.contracts.decision import ActionSpec
        output={'type':'object','properties':{'count':{'type':'integer'}},'required':['count']}
        for index,validity in enumerate((3_000_000_000,180_000_000_000)):
            name='plan'+str(index)
            self.h.registry.register_typed(ActionSpec(name,Parameters,output_schema=output,
                output_max_age_ns=validity,external_lifecycle='typed_only'),Factory())
            d=definition(nodes=[node('start','Start'),node('plan','Action',action_type=name),
                node('travel','Wait',parameters={'duration_s':5.}),
                node('consume','Action',action_type='ok',input_bindings={'count':{'ref':'node.plan.output.count'}}),node('end','End')],
                edges=[edge(a,b) for a,b in zip(['start','plan','travel','consume'],['plan','travel','consume','end'])])
            d['version']='1.0.'+str(index)
            identifier=self.start(d);self.h.ticks(180);view=self.h.engine.view(identifier)
            self.assertEqual(view['state'],'UNKNOWN' if index==0 else 'SUCCEEDED',view['error'])
            if index:
                execution=next(e for e in view['studio']['executions'] if e['node_id']=='consume')
                fact=execution['inputs']['count']
                self.assertGreater(self.h.clock().monotonic_ns-fact['observed_at']['monotonic_ns'],5_000_000_000)
                self.assertEqual(fact['valid_for_ns'],validity)
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
        parent=definition(nodes=[node('start','Start'),node('parallel','Parallel'),
            node('work','SubMission',sub_mission=dict(mission_id='child',version='1.0.0'),parameters={'item':3},output_bindings={'count':{'ref':'mission.result'}}),
            node('wait','Wait',parameters={'duration_s':.05}),node('end','End')],edges=[edge('start','parallel'),edge('parallel','work','branch:0'),edge('parallel','wait','branch:1'),edge('parallel','end')],
            blackboard={'result':dict(schema={'type':'integer'},default=0)})
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
        execution=next(e for e in v['studio']['executions'] if e['node_id']=='work' and e['action_id'])
        self.assertEqual(execution['inputs']['count']['value'],4);self.assertEqual(execution['inputs']['count']['source'],'runtime_override')
        self.assertTrue(execution['scope_id'].startswith('node:'))
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
    def test_takeover_at_safe_boundary_releases_then_requires_explicit_validated_resume(self):
        d=definition(execution_policy=dict(timeout_s=30,breakpoints=['work']));i=self.start(d);self.h.ticks(3)
        self.h.engine.debug(i,'takeover');self.h.ticks(3);v=self.h.engine.view(i)
        self.assertEqual(v['state'],'SUSPENDED');self.assertTrue(v['release_safe']);self.assertTrue(v['studio']['takeover']['resumable'])
        old_group=v['resource_group_id'];self.h.ticks(5);self.assertFalse(self.h.engine.view(i)['action_ids'])
        self.h.engine.debug(i,'resume');self.h.ticks(15);v=self.h.engine.view(i)
        self.assertEqual(v['state'],'SUCCEEDED');self.assertNotEqual(v['resource_group_id'],old_group)
    def test_interrupted_active_action_does_not_silently_restart_after_takeover(self):
        d=definition();d['nodes'][1]['action_type']='stream';i=self.start(d);self.h.ticks(4)
        self.h.engine.debug(i,'takeover');self.h.ticks(10);v=self.h.engine.view(i)
        self.assertEqual(v['state'],'SUSPENDED');self.assertTrue(v['release_safe']);self.assertFalse(v['studio']['takeover']['resumable'])
        self.assertEqual(len(v['action_ids']),1)
        with self.assertRaises(ValueError):self.h.engine.debug(i,'resume')
        self.h.ticks(5);self.assertEqual(len(self.h.engine.view(i)['action_ids']),1)
    def test_parallel_join_commits_disjoint_outputs_and_any_discards_cancelled_branch(self):
        for completion in ('all','any'):
            nodes=[node('start','Start'),node('parallel','Parallel',execution_policy=dict(completion=completion,max_concurrency=2)),
                node('a','Action',action_type='ok',parameters={'count':3},output_bindings={'count':{'ref':'mission.a'}}),
                node('b','Action',action_type='ok',parameters={'count':1},output_bindings={'count':{'ref':'mission.b'}}),node('end','End')]
            edges=[edge('start','parallel'),edge('parallel','a','branch:0'),edge('parallel','b','branch:1'),edge('parallel','end')]
            if completion=='any':nodes.append(node('stream','Action',action_type='stream'));edges.append(edge('b','stream'))
            d=definition(nodes=nodes,edges=edges,blackboard={name:dict(schema={'type':'integer'},default=0) for name in ('a','b')});d['version']='1.0.'+str(len(self.h.engine.views()))
            i=self.start(d);self.h.ticks(40);v=self.h.engine.view(i);self.assertEqual(v['state'],'SUCCEEDED',v['error'])
            values={c['name']:c['data']['value'] for c in v['studio']['blackboard']['values'] if c['scope_id']=='mission'}
            self.assertEqual(values['a'],3);self.assertEqual(values['b'],1 if completion=='all' else 0)
            if completion=='any':self.assertEqual(next(e for e in v['studio']['executions'] if e['node_id']=='stream')['state'],'CANCELLED')

