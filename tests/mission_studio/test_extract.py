import unittest
from dataclasses import replace
from tests.mission_graph import test_graph as legacy
from tests.mission_studio.test_compiler import definition,node,edge
from vehicle_autonomy.app.mission_designer.studio_extract import extract
from vehicle_autonomy.engine.mission.graph import validate


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.h=legacy.GraphTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        entry=self.h.registry.resolve_typed('ok');self.h.registry.register_typed(replace(entry.spec,version='1.0.1',output_schema={'type':'object','properties':{'count':{'type':'integer'}},'required':['count']}),entry.factory)
    def test_typed_input_output_and_downstream_reference_survive_extraction(self):
        d=definition(nodes=[node('start','Start'),node('a','Action',action_type='ok',input_bindings={'count':{'ref':'mission.value'}}),
            node('b','Action',action_type='ok',input_bindings={'count':{'ref':'node.a.output.count'}},output_bindings={'count':{'ref':'mission.result'}}),node('end','End')],
            edges=[edge('start','a'),edge('a','b'),edge('b','end')],blackboard={'value':{'schema':{'type':'integer'},'default':3},'result':{'schema':{'type':'integer'},'default':0}})
        source=validate(d,self.h.registry,{'v':self.h.driver}).to_dict()['studio']['definition']
        child,parent=extract(source,['a'],'child','Extracted',self.h.registry)
        compiled=validate(parent,self.h.registry,{'v':self.h.driver},resolve=lambda *_:child)
        i=self.h.engine.start(compiled)['id'];self.h.ticks(40);v=self.h.engine.view(i)
        self.assertEqual(v['state'],'SUCCEEDED',v['error'])
        result=next(c for c in v['studio']['blackboard']['values'] if c['scope_id']=='mission' and c['name']=='result')
        self.assertEqual(result['data']['value'],3);self.assertEqual(source['nodes'][1]['node_id'],'a')
    def test_open_selection_or_unsupported_composite_is_rejected(self):
        d=validate(definition(),self.h.registry,{'v':self.h.driver}).to_dict()['studio']['definition']
        with self.assertRaises(ValueError):extract(d,['start'],'child','Child',self.h.registry)
        with self.assertRaises(ValueError):extract(d,['work','absent'],'child','Child',self.h.registry)
