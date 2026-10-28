from copy import deepcopy
from dataclasses import replace
import unittest
from tests.mission_graph import test_graph as legacy
from vehicle_autonomy.engine.mission.graph import validate
from vehicle_autonomy.engine.mission.studio_graph import migrate


def node(i,t,**kw):return dict(node_id=i,type=t,**kw)
def edge(a,b,port='next',i=None):return dict(edge_id=i or 'e_'+a+'_'+b,source=a,target=b,port=port)
def definition(nodes=None,edges=None,**kw):
    return dict(schema_version=2,mission_id='studio',revision=0,version='1.0.0',name='Studio',target='v',supported_vehicles=['rover'],
        nodes=nodes or [node('start','Start'),node('work','Action',action_type='ok'),node('end','End')],
        edges=edges or [edge('start','work'),edge('work','end')],**kw)


class CompilerTests(unittest.TestCase):
    def setUp(self):
        self.h=legacy.GraphTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.registry=self.h.registry;self.drivers={'v':self.h.driver}
    def compile(self,d,**kw):return validate(d,self.registry,self.drivers,**kw).to_dict()
    def test_linear_graph_compiles_pinned_versions_and_roundtrips(self):
        d=definition();c=self.compile(d)
        self.assertEqual(c['studio']['definition']['nodes'][1]['action_contract_version'],'1.0.0')
        self.assertEqual(self.compile(c),c);self.assertNotIn('action_contract_version',d['nodes'][1])
        c['nodes'][1]['source_node_id']='tamper'
        with self.assertRaises(ValueError):self.compile(c)
    def test_bad_edges_cycle_orphans_types_and_missing_parameters(self):
        cases=[]
        d=definition();d['edges'][0]['target']='absent';cases.append(d)
        d=definition();d['edges'].append(edge('work','start','failure'));cases.append(d)
        d=definition();d['nodes'].append(node('orphan','Wait'));cases.append(d)
        d=definition();d['nodes'][1]['input_bindings']={'count':{'ref':'mission.value'}};d['blackboard']={'value':dict(schema={'type':'string'},default='bad')};cases.append(d)
        d=definition();d['nodes'][1]['parameters']={'count':True};cases.append(d)
        for d in cases:
            with self.subTest(d=d),self.assertRaises((ValueError,TypeError)):self.compile(d)
    def test_foreach_requires_typed_collection_and_bounded_body(self):
        d=definition(nodes=[node('start','Start'),node('loop','ForEach',execution_policy=dict(collection={'ref':'mission.items'},max_iterations=2)),
            node('work','Action',action_type='ok',input_bindings={'count':{'ref':'loop.current_item'}}),node('end','End')],
            edges=[edge('start','loop'),edge('loop','work','body'),edge('loop','end')],blackboard={'items':dict(schema={'type':'array','items':{'type':'integer'}},default=[1,2])})
        c=self.compile(d);self.assertEqual(next(n for n in c['nodes'] if n['type']=='ForEach')['max_iterations'],2)
        d['nodes'][1]['execution_policy']['max_iterations']=100
        with self.assertRaises(ValueError):self.compile(d)
    def test_retry_requires_explicit_action_contract(self):
        d=definition();d['nodes'][1]['failure_policy']=dict(mode='retry',attempts=2)
        with self.assertRaises(ValueError):self.compile(d)
        entry=self.registry.resolve_typed('ok');self.registry.register_typed(replace(entry.spec,version='1.0.1',retryable=True),entry.factory)
        c=self.compile(d);self.assertTrue(any(n['type']=='Retry' for n in c['nodes']))
    def test_upstream_binding_and_declared_output_types(self):
        entry=self.registry.resolve_typed('ok');self.registry.register_typed(replace(entry.spec,version='1.0.1',output_schema={'type':'object','properties':{'count':{'type':'integer'}},'required':['count']}),entry.factory)
        d=definition(nodes=[node('start','Start'),node('first','Action',action_type='ok'),node('second','Action',action_type='ok',input_bindings={'count':{'ref':'node.first.output.count'}}),node('end','End')],edges=[edge('start','first'),edge('first','second'),edge('second','end')])
        self.compile(d);d['nodes'][1]['input_bindings']={'count':{'ref':'node.second.output.count'}}
        with self.assertRaises(ValueError):self.compile(d)
    def test_explicit_join_does_not_duplicate_shared_execution(self):
        d=definition(nodes=[node('start','Start'),node('parallel','Parallel',execution_policy={'join_id':'join','completion':'all'}),node('a','Wait'),node('b','Wait'),node('join','Join'),node('end','End')],
            edges=[edge('start','parallel'),edge('parallel','a','branch:0'),edge('parallel','b','branch:1'),edge('a','join'),edge('b','join'),edge('join','end')])
        c=self.compile(d);self.assertEqual(len({n['id'] for n in c['nodes']}),len(c['nodes']))
    def test_submission_pins_and_recursion_are_validated(self):
        child=definition();child['mission_id']='child'
        d=definition();d['nodes'][1]=node('work','SubMission',sub_mission=dict(mission_id='child',version='1.0.0'))
        c=self.compile(d,resolve=lambda i,v:child);self.assertIn('child@1.0.0',c['studio']['dependencies']);self.assertEqual(self.compile(c),c)
        child['nodes'][1]=node('work','SubMission',sub_mission=dict(mission_id='child',version='1.0.0'))
        with self.assertRaises(ValueError):self.compile(d,resolve=lambda i,v:child)
    def test_legacy_linear_migration_is_explicit_copy(self):
        old=dict(schema_version=1,id='old',name='Old',version='1.0.0',target='v',root='root',nodes=[dict(id='root',type='Sequence',children=['a','b']),dict(id='a',type='Action',action='ok',parameters={}),dict(id='b',type='Wait',duration_s=.1)])
        before=deepcopy(old);self.compile(migrate(old));self.assertEqual(old,before)
    def test_migration_keeps_observation_bindings_and_scopes_guard(self):
        old=dict(schema_version=1,id='old',name='Old',version='1.0.0',target='v',root='root',blackboard={'value':3},nodes=[
            dict(id='root',type='Sequence',children=['work','guard']),dict(id='work',type='Action',action='ok',parameters={'count':{'$query':dict(source='blackboard',path='value')}}),
            dict(id='guard',type='Condition',expression=dict(op='eq',source='blackboard',path='value',value=3))])
        migrated=migrate(old,registry=self.registry,drivers=self.drivers);compiled=self.compile(migrated)
        self.assertTrue(any(n['type']=='Condition' for n in compiled['nodes']))
        self.assertEqual(next(n for n in migrated['nodes'] if n['type']=='Action')['input_bindings']['count']['ref'],'mission.value')

