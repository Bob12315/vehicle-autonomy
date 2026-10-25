from copy import deepcopy
from dataclasses import replace
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.action_system.test_runtime import Clock, Driver, Factory, Parameters, ready
from vehicle_autonomy.contracts.action import ActionKind, ActionSafety
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.decision import ActionSpec
from vehicle_autonomy.contracts.mission import BlackboardValue, Truth
from vehicle_autonomy.engine.action.registry import ActionRegistry
from vehicle_autonomy.engine.action.manager import ActionRuntime
from vehicle_autonomy.engine.mission.graph import validate
from vehicle_autonomy.engine.mission.journal import MissionJournal
from vehicle_autonomy.engine.mission.graph_runtime import MissionGraphRuntime
from vehicle_autonomy.world.model.mission_inputs import LocalEvents, evaluate


def leaf(identifier='a', name='ok', **kw): return dict(id=identifier, type='Action', action=name, parameters={}, **kw)
def graph(*nodes, root=None, **kw):
    return dict(schema_version=1, id='test', name='Test', version='1.0.0', target='v',
                root=root or nodes[0]['id'], nodes=list(nodes), **kw)


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.clock=Clock();self.driver=Driver();self.events=LocalEvents()
        self.driver.snapshot=lambda:SimpleNamespace(published_at=self.clock())
        self.registry=ActionRegistry()
        for name,continuous in [('ok',False),('stream',True)]:
            self.registry.register_typed(ActionSpec(name,Parameters,kind=ActionKind.CONTINUOUS if continuous else ActionKind.GOAL,
                external_lifecycle='typed_only'),Factory(continuous=continuous))
        self.actions=ActionRuntime(self.registry,{'v':self.driver},clock=self.clock)
        self.journal=MissionJournal(Path(self.temp.name)/'journal');self.addCleanup(self.journal.close)
        self.engine=MissionGraphRuntime(self.actions,self.journal,self.events,clock=self.clock)
    def ticks(self,n=20,step=.05):
        for _ in range(n):self.engine.tick();self.actions.tick();self.clock.advance(step)
    def run_graph(self,d,**kw):return self.engine.start(d,**kw)['id']
    def test_sequence_pins_versions_and_separates_three_identities(self):
        d=graph(dict(id='root',type='Sequence',children=['a','b']),leaf('a'),leaf('b'))
        i=self.run_graph(d);d['nodes'][1]['action']='not-registered';self.ticks()
        v=self.engine.view(i);self.assertEqual(v['state'],'SUCCEEDED')
        self.assertTrue(v['release_safe']);self.assertEqual(len(v['action_ids']),2)
        n=next(n for n in v['nodes'] if n['id']=='a')
        self.assertEqual(len({i,n['execution_id'],n['action_id']}),3)
        self.assertEqual(v['spec']['nodes'][1]['action_version'],'1.0.0')
    def test_published_version_immutable_but_new_version_loads(self):
        i=self.run_graph(graph(leaf()));self.ticks()
        d=graph(leaf())
        d['nodes'][0]['parameters']={'count':3}
        with self.assertRaises(ValueError):self.engine.start(d)
        d['version']='1.0.1';i2=self.run_graph(d);self.ticks();self.assertEqual(self.engine.view(i2)['state'],'SUCCEEDED')
        self.assertEqual(len(self.journal.data['versions']),2)
    def test_invalid_schema_edges_cycles_orphans_and_unknown_fields(self):
        cases=[]
        for k,v in [('schema_version',2),('schema_version',True),('version','1'),('target','absent'),('unknown',1)]:
            d=graph(leaf());d[k]=v;cases.append(d)
        cases += [graph(dict(id='a',type='Sequence',children=['a'])),graph(leaf(),leaf('orphan')),
                  graph(dict(id='a',type='Sequence',children=['no'])),graph(dict(id='a',type='Repeat',count=100,children=['b']),leaf('b')),
                  graph(dict(id='a',type='Action',action='missing')),graph(dict(id='a',type='Wait',duration_s=float('nan')))]
        for d in cases:
            with self.subTest(d=d), self.assertRaises((ValueError,TypeError)):validate(d,self.registry,{'v':self.driver})
        self.assertEqual(self.driver.writes,[])
    def test_resource_declaration_must_match_registry(self):
        with self.assertRaises(ValueError):validate(graph(leaf(),resources=['vehicle.motion']),self.registry,{'v':self.driver})
    def test_repeat_is_bounded_and_has_new_execution_id(self):
        i=self.run_graph(graph(dict(id='r',type='Repeat',count=3,children=['a']),leaf()))
        self.ticks(40);v=self.engine.view(i)
        self.assertEqual(v['state'],'SUCCEEDED');self.assertEqual(len(v['action_ids']),3)
        self.assertEqual(len(set(v['action_ids'])),3)
    def test_wait_and_timeout_cancel_an_actual_running_action(self):
        i=self.run_graph(graph(dict(id='t',type='Timeout',timeout_s=.3,children=['a']),leaf(name='stream')))
        self.ticks();v=self.engine.view(i)
        self.assertEqual(v['state'],'TIMED_OUT');self.assertTrue(v['release_safe'])
        self.assertEqual(self.actions.view(v['action_ids'][0])['state'],'CANCELLED')
    def test_parallel_any_cleans_background_before_terminal(self):
        i=self.run_graph(graph(dict(id='p',type='Parallel',completion='any',failure='fail_fast',children=['a','b']),
            leaf(),leaf('b','stream')))
        self.ticks();v=self.engine.view(i)
        self.assertEqual(v['state'],'SUCCEEDED');self.assertTrue(v['release_safe'])
        self.assertEqual([self.actions.view(a)['state'] for a in v['action_ids']],['SUCCEEDED','CANCELLED'])
    def test_parallel_main_and_all_policies(self):
        for completion in ('main','all'):
            d=graph(dict(id='p',type='Parallel',completion=completion,children=['a','b']),leaf(),leaf('b'))
            d['version']='1.0.'+str(len(self.engine.views()))
            i=self.run_graph(d);self.ticks();self.assertEqual(self.engine.view(i)['state'],'SUCCEEDED')
    def test_unknown_cancel_holds_and_blocks_new_mission(self):
        self.driver.safety=ActionSafety(False,False,'remote stop unknown')
        i=self.run_graph(graph(leaf(name='stream')));self.ticks(2);self.engine.cancel(i);self.ticks()
        v=self.engine.view(i);self.assertEqual(v['state'],'UNKNOWN');self.assertFalse(v['release_safe'])
        with self.assertRaises(ValueError):self.engine.start(graph(leaf()))
    def test_fallback_cannot_treat_unknown_as_failed(self):
        d=graph(dict(id='f',type='Fallback',children=['c','a']),
                dict(id='c',type='Condition',expression=dict(op='eq',source='world',path='vehicle.operation.armed',value=True)),leaf())
        i=self.run_graph(d);self.ticks();v=self.engine.view(i)
        self.assertEqual(v['state'],'UNKNOWN');self.assertEqual(v['action_ids'],[])
    def test_fallback_on_known_false_runs_recovery(self):
        d=graph(dict(id='f',type='Recovery',children=['c','a']),dict(id='c',type='Condition',
            expression=dict(op='eq',source='blackboard',path='ready',value=True)),leaf(),blackboard={'ready':False})
        i=self.run_graph(d);self.ticks();self.assertEqual(self.engine.view(i)['state'],'SUCCEEDED')
    def test_event_identity_age_and_pre_subscription_events(self):
        self.events.publish('old','go',{},self.clock())
        i=self.run_graph(graph(dict(id='e',type='Event',event='go',children=['a']),leaf()))
        self.ticks(2);self.assertEqual(self.engine.view(i)['action_ids'],[])
        self.assertFalse(self.events.publish('old','go',{},self.clock()))
        self.events.publish('new','go',{},self.clock());self.ticks()
        self.assertEqual(self.engine.view(i)['state'],'SUCCEEDED')
        consumed=[e for e in self.engine.view(i)['history'] if e['event']=='event_consumed']
        self.assertEqual([e['event_id'] for e in consumed],['new'])
    def test_reactive_waits_for_safe_cancellation(self):
        i=self.run_graph(graph(dict(id='r',type='Reactive',event='go',children=['main','response']),
            leaf('main','stream'),leaf('response')))
        self.ticks(2);self.events.publish('one','go',{},self.clock());self.ticks()
        v=self.engine.view(i);self.assertEqual(v['state'],'SUCCEEDED')
        self.assertEqual([self.actions.view(a)['state'] for a in v['action_ids']],['CANCELLED','SUCCEEDED'])
    def test_reactive_unknown_never_starts_reaction(self):
        self.driver.safety=ActionSafety(False,False,'stop unconfirmed')
        i=self.run_graph(graph(dict(id='r',type='Reactive',event='go',children=['main','response']),leaf('main','stream'),leaf('response')))
        self.ticks(2);self.events.publish('one','go',{},self.clock());self.ticks()
        self.assertEqual(self.engine.view(i)['state'],'UNKNOWN');self.assertEqual(len(self.engine.view(i)['action_ids']),1)
    def test_missing_stale_future_domain_quality_frame_are_unknown(self):
        now=self.clock();e=dict(op='eq',source='blackboard',path='x',value=1)
        for value in [None,BlackboardValue(1,replace(now,monotonic_ns=now.monotonic_ns+1),100),
                BlackboardValue(1,replace(now,clock_domain_id='other'),100),
                BlackboardValue(1,now,1,quality='INVALID'),BlackboardValue(1,replace(now,monotonic_ns=0),1)]:
            self.assertIs(evaluate(e,None,{'x':value},now),Truth.UNKNOWN)
        e['frame']='odom'
        self.assertIs(evaluate(e,None,{'x':BlackboardValue(1,now,100,frame='map')},now),Truth.UNKNOWN)
        self.assertIs(evaluate(e,None,{'x':BlackboardValue(1,now,100,frame='odom')},now),Truth.TRUE)
        self.assertIs(evaluate(dict(op='not',arg=e),None,{},now),Truth.UNKNOWN)
    def test_unknown_not_boolean_coerced_or_eval_executed(self):
        for e in [dict(op='eval',value='__import__("os")'),dict(op='eq',source='world',path='__dict__',value=1)]:
            with self.assertRaises(ValueError):validate(graph(dict(id='c',type='Condition',expression=e)),self.registry,{'v':self.driver})
        self.assertIs(evaluate(dict(op='eq',source='blackboard',path='x',value=True),None,
            {'x':BlackboardValue(1,self.clock(),100)},self.clock()),Truth.UNKNOWN)
    def test_event_budget_is_bounded_without_forgetting_replay(self):
        source=LocalEvents(2)
        source.publish('a','x',1,self.clock());source.publish('b','x',1,self.clock())
        self.clock.advance(60)
        with self.assertRaises(ValueError):source.publish('c','x',1,self.clock())
        self.assertFalse(source.publish('a','x',1,self.clock()));self.assertEqual(source.read(0,'x',self.clock()),())
    def test_restart_preserves_unknown_and_never_submits_action(self):
        i=self.run_graph(graph(leaf(name='stream')));self.ticks(2)
        self.journal.close();j=MissionJournal(Path(self.temp.name)/'journal');self.addCleanup(j.close)
        new_actions=ActionRuntime(self.registry,{'v':self.driver},clock=self.clock)
        engine=MissionGraphRuntime(new_actions,j,self.events,clock=self.clock)
        self.assertEqual(engine.view(i)['state'],'UNKNOWN');self.assertFalse(engine.view(i)['release_safe'])
        engine.tick();new_actions.tick();self.assertEqual(new_actions.views(),[])
        with self.assertRaises(ValueError):engine.start(graph(leaf()))
    def test_journal_competition_corruption_missing_and_partial_write(self):
        with self.assertRaises(ValueError):MissionJournal(Path(self.temp.name)/'journal')
        original=(self.journal.path/'state.json').read_bytes()
        self.journal.close();(Path(self.temp.name)/'journal/state.json').write_bytes(original[:20])
        with self.assertRaises((ValueError,TypeError)):MissionJournal(Path(self.temp.name)/'journal')
        (Path(self.temp.name)/'journal/state.json').unlink()
        with self.assertRaises(FileNotFoundError):MissionJournal(Path(self.temp.name)/'journal')
    def test_partial_persistence_does_not_start_any_action(self):
        with patch('vehicle_autonomy.engine.action.durable.os.write',return_value=1):
            with self.assertRaises(OSError):self.run_graph(graph(leaf()))
        self.assertEqual(self.actions.views(),[]);self.assertEqual(self.driver.writes,[])

    def test_bound_parameters_use_original_blackboard_stamp_and_registry_limits(self):
        d=graph(leaf(),blackboard={'source':{'count':2}})
        d['nodes'][0]['parameters']={'count':{'$query':dict(source='blackboard',path='source.count',offset=1,max_age_s=3)}}
        i=self.run_graph(d);self.ticks()
        a=self.actions.view(self.engine.view(i)['action_ids'][0])
        self.assertEqual(a['state'],'SUCCEEDED');self.assertEqual(a['parameters']['count'],3)
    def test_missing_parameter_binding_waits_bounded_then_unknown_without_action(self):
        d=graph(leaf());d['nodes'][0]['parameters']={'count':{'$query':dict(source='blackboard',path='absent')}}
        i=self.run_graph(d);self.ticks(2);self.assertEqual(self.engine.view(i)['state'],'RUNNING')
        self.clock.advance(3.1);self.ticks()
        self.assertEqual(self.engine.view(i)['state'],'UNKNOWN');self.assertEqual(self.actions.views(),[])
    def test_event_repeat_consumes_each_identity_only_once(self):
        i=self.run_graph(graph(dict(id='r',type='Repeat',count=2,children=['e']),
            dict(id='e',type='Event',event='go',children=['a']),leaf()))
        self.events.publish('one','go',1,self.clock());self.ticks(15)
        self.assertEqual(self.engine.view(i)['state'],'RUNNING');self.assertEqual(len(self.engine.view(i)['action_ids']),1)
        self.events.publish('two','go',2,self.clock());self.ticks()
        self.assertEqual(self.engine.view(i)['state'],'SUCCEEDED');self.assertEqual(len(self.engine.view(i)['action_ids']),2)
    def test_parallel_conflicts_rejected_before_admission(self):
        from vehicle_autonomy.contracts.action import ActionResource
        spec=self.registry.resolve_typed('ok').spec
        self.registry.register_typed(replace(spec,name='exclusive',resources=(ActionResource('motion'),)),Factory())
        d=graph(dict(id='p',type='Parallel',children=['a','b']),leaf('a','exclusive'),leaf('b','exclusive'))
        with self.assertRaises(ValueError):self.run_graph(d)
        self.assertEqual(self.actions.views(),[]);self.assertEqual(self.driver.writes,[])
    def test_unknown_branch_cannot_hide_new_motion_or_external_job(self):
        d=graph(dict(id='c',type='Condition',children=['a','b','u'],expression=dict(op='eq',source='world',path='missing',value=1)),leaf('a'),leaf('b'),leaf('u'))
        with self.assertRaises(ValueError):self.run_graph(d)
    def test_invalid_query_binding_language_rejected(self):
        for q in [dict(source='python',path='x'),dict(source='world',path='__dict__'),dict(source='world',path='x',offset=float('inf')),dict(source='world',path='x',code='unsafe')]:
            d=graph(leaf());d['nodes'][0]['parameters']={'count':{'$query':q}}
            with self.subTest(q=q),self.assertRaises(ValueError):self.run_graph(d)

    def test_mission_reserves_resources_between_children_against_direct_runtime_submit(self):
        from vehicle_autonomy.contracts.action import ActionResource
        from vehicle_autonomy.contracts.effects.vehicle import ArmEffect
        self.registry.register_typed(ActionSpec('writer',Parameters,effect_types=(ArmEffect,),
            external_lifecycle='typed_only',resources=(ActionResource('vehicle.motion',conflict_group='vehicle.control'),)),Factory(emit=True))
        d=graph(dict(id='root',type='Sequence',children=['w','a']),dict(id='w',type='Wait',duration_s=2),leaf('a','writer'))
        self.run_graph(d,allow_send=True)
        intruder=self.actions.submit('writer','v',allow_send=True);self.actions.tick()
        self.assertEqual(intruder['state'],'REJECTED')
        self.assertEqual(self.driver.writes,[])

    def test_active_mission_continuation_cannot_be_stolen_but_completed_handoff_works(self):
        from vehicle_autonomy.contracts.action import ActionResource
        from vehicle_autonomy.contracts.effects.vehicle import ArmEffect
        self.registry.register_typed(ActionSpec('writer',Parameters,effect_types=(ArmEffect,),external_lifecycle='typed_only',
            resources=(ActionResource('vehicle.motion',conflict_group='vehicle.control'),)),Factory(emit=True))
        self.driver.safety=ActionSafety(False,True,'native flight')
        i=self.run_graph(graph(dict(id='root',type='Sequence',children=['a','w','b']),leaf('a','writer'),
            dict(id='w',type='Wait',duration_s=1),leaf('b','writer')),allow_send=True)
        self.ticks(6)
        first=self.engine.view(i)['action_ids'][0]
        intruder=self.actions.submit('writer','v',allow_send=True,continuation_of=first)
        self.actions.tick();self.assertEqual(intruder['state'],'REJECTED');self.assertEqual(len(self.driver.writes),1)
        self.ticks(40);v=self.engine.view(i)
        self.assertEqual(v['state'],'SUCCEEDED');self.assertFalse(v['release_safe']);self.assertTrue(v['continuation_allowed'])
        a=self.actions.submit('writer','v',allow_send=True,continuation_of=v['continuation_of']);self.actions.tick();self.actions.tick();self.actions.tick()
        self.assertEqual(self.actions.view(a['id'])['state'],'SUCCEEDED')
        self.assertTrue(self.engine.view(i)['release_safe']);self.assertFalse(self.engine.view(i)['continuation_allowed'])
        self.assertEqual(len(self.driver.writes),3)
    def test_restarted_group_blocks_direct_runtime_even_before_new_mission(self):
        from vehicle_autonomy.contracts.action import ActionResource
        from vehicle_autonomy.contracts.effects.vehicle import ArmEffect
        self.registry.register_typed(ActionSpec('writer',Parameters,effect_types=(ArmEffect,),external_lifecycle='typed_only',
            resources=(ActionResource('vehicle.motion'),)),Factory(emit=True))
        i=self.run_graph(graph(dict(id='root',type='Sequence',children=['w','a']),dict(id='w',type='Wait',duration_s=10),leaf('a','writer')),allow_send=True)
        self.journal.close();j=MissionJournal(Path(self.temp.name)/'journal');self.addCleanup(j.close)
        new=ActionRuntime(self.registry,{'v':self.driver},clock=self.clock)
        restarted=MissionGraphRuntime(new,j,self.events,clock=self.clock)
        a=new.submit('writer','v',allow_send=True);new.tick()
        self.assertEqual(a['state'],'REJECTED');self.assertEqual(self.driver.writes,[])
        self.assertTrue(new.resource_view());self.assertEqual(restarted.view(i)['state'],'UNKNOWN')
    def test_blackboard_does_not_refresh_nested_old_world_observation(self):
        from vehicle_autonomy.contracts.core.serialization import to_json_value
        self.clock.advance(5);now=self.clock();old=replace(now,monotonic_ns=now.monotonic_ns-4_000_000_000)
        value={'world':{'published_at':to_json_value(old),'vehicle':{'reported_pose':{'captured_at':to_json_value(old),
            'frame_id':'odom','value':{'position':{'x':1.}}}}}}
        bb={'out':BlackboardValue(value,now,3_000_000_000,source='action:result')}
        e=dict(op='gt',source='blackboard',path='out.world.vehicle.reported_pose.value.position.x',value=0.,frame='odom')
        self.assertIs(evaluate(e,None,bb,now),Truth.UNKNOWN)

    def test_unchanged_wait_does_not_repeat_durable_commits(self):
        i=self.run_graph(graph(dict(id='w',type='Wait',duration_s=1)))
        with patch.object(self.journal.record,'write',wraps=self.journal.record.write) as write:
            self.ticks(5)
            self.assertEqual(write.call_count,1)
            self.clock.advance(1);self.ticks(2)
            self.assertEqual(write.call_count,2)
            self.assertEqual(self.engine.view(i)['state'],'SUCCEEDED')

    def test_copied_mission_identity_is_not_a_membership_permit(self):
        from vehicle_autonomy.engine.action.mission_groups import MissionPermit
        i=self.run_graph(graph(dict(id='w',type='Wait',duration_s=1)))
        real=self.engine.runs[i].permit
        forged=MissionPermit(real.id,real.target,real.resources)
        with self.assertRaises(ValueError):
            self.actions.submit('ok','v',mission_permit=forged)
        self.assertEqual(self.actions.views(),[])
        self.assertEqual(self.driver.writes,[])

    def test_member_cannot_exceed_pinned_mission_resources(self):
        from vehicle_autonomy.contracts.action import ActionResource
        from vehicle_autonomy.contracts.effects.vehicle import ArmEffect
        self.registry.register_typed(ActionSpec('writer',Parameters,effect_types=(ArmEffect,),
            external_lifecycle='typed_only',resources=(ActionResource('vehicle.motion'),)),Factory(emit=True))
        i=self.run_graph(graph(dict(id='w',type='Wait',duration_s=1)))
        a=self.actions.submit('writer','v',allow_send=True,mission_permit=self.engine.runs[i].permit)
        self.actions.tick()
        self.assertEqual(a['state'],'REJECTED')
        self.assertEqual(self.driver.writes,[])


if __name__=='__main__':unittest.main()
