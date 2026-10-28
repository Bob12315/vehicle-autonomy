import unittest
from dataclasses import replace
from tests.action_system.test_runtime import Clock
from vehicle_autonomy.contracts.mission import BlackboardValue
from vehicle_autonomy.engine.mission.blackboard import Blackboard,declaration


def typed(kind,default,**kw):return dict(schema=dict(type=kind),default=default,**kw)


class BlackboardTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.b=Blackboard(dict(count=typed('integer',0),other=typed('integer',0),
            items=dict(schema=dict(type='array',items=dict(type='integer')),default=[])),self.clock())
    def test_type_scope_and_original_provenance(self):
        sid=self.b.create('submission','mission',dict(input=typed('integer',1)),self.clock())
        self.b.write(sid,'submission.input',2,self.clock(),'node:test')
        self.assertEqual(self.b.read(sid,dict(ref='submission.input'),self.clock())[0],2)
        self.assertEqual(self.b.read('mission',dict(ref='mission.count'),self.clock())[0],0)
        with self.assertRaises((TypeError,ValueError)):self.b.write(sid,'mission.count',True,self.clock(),'node:bad')
        with self.assertRaises(ValueError):self.b.write(sid,'mission.missing',1,self.clock(),'node:bad')
    def test_node_outputs_are_isolated_between_iterations(self):
        a=self.b.create('loop','mission',{},self.clock());b=self.b.create('loop','mission',{},self.clock())
        self.b.output(a,'detect',dict(value=1),self.clock(),'node:a');self.b.output(b,'detect',dict(value=2),self.clock(),'node:b')
        self.assertEqual(self.b.read(a,dict(ref='node.detect.output.value'),self.clock())[0],1)
        self.assertEqual(self.b.read(b,dict(ref='node.detect.output.value'),self.clock())[0],2)
        with self.assertRaises(ValueError):self.b.read('mission',dict(ref='node.detect.output.value'),self.clock())
        self.b.output('mission','detect',dict(value=99),self.clock(),'outer')
        child=self.b.create('submission','mission',{},self.clock())
        with self.assertRaises(ValueError):self.b.read(child,dict(ref='node.detect.output.value'),self.clock())
    def test_stale_future_domain_quality_and_frame_are_not_promoted(self):
        now=self.clock()
        for original in (BlackboardValue(2,now,10),BlackboardValue(2,replace(now,monotonic_ns=now.monotonic_ns+1),100),
            BlackboardValue(2,replace(now,clock_domain_id='other'),100),BlackboardValue(2,now,100,quality='INVALID')):
            self.b.write('mission','mission.count',2,now,'copy',original=original)
            self.clock.advance(.01)
            with self.assertRaises(ValueError):self.b.read('mission',dict(ref='mission.count'),self.clock())
        self.b.write('mission','mission.count',2,self.clock(),'fresh')
        with self.assertRaises(ValueError):self.b.read('mission',dict(ref='mission.count',frame='map'),self.clock())
    def test_parallel_staging_and_conflict_are_atomic(self):
        a=self.b.create('parallel','mission',{},self.clock());b=self.b.create('parallel','mission',{},self.clock())
        self.b.write(a,'mission.count',1,self.clock(),'a');self.b.write(b,'mission.count',2,self.clock(),'b')
        self.assertEqual(self.b.read(a,dict(ref='mission.count'),self.clock())[0],1)
        self.assertEqual(self.b.read('mission',dict(ref='mission.count'),self.clock())[0],0)
        with self.assertRaises(ValueError):self.b.commit([a,b])
        self.assertEqual(self.b.read('mission',dict(ref='mission.count'),self.clock())[0],0)
    def test_parallel_disjoint_commit_and_append_keep_original_time(self):
        a=self.b.create('parallel','mission',{},self.clock());b=self.b.create('parallel','mission',{},self.clock());start=self.clock()
        self.b.write(a,'mission.count',1,start,'a');self.b.write(b,'mission.other',2,start,'b');self.b.commit([a,b])
        self.assertEqual(self.b.read('mission',dict(ref='mission.other'),start)[0],2)
        self.clock.advance(1);self.b.write('mission','mission.items',3,self.clock(),'append',mode='append')
        self.assertEqual(self.b.read('mission',dict(ref='mission.items.0'),self.clock())[0],3)
        self.assertEqual(self.b.cells['mission','items'].data.observed_at,start)
    def test_readonly_large_values_and_spatial_declarations(self):
        with self.assertRaises(ValueError):declaration(typed('object',{},category='pose'))
        with self.assertRaises(ValueError):declaration(dict(schema={'$ref':'https://invalid.example/schema'}))
        b=Blackboard(dict(external=typed('string','known',readonly=True)),self.clock())
        with self.assertRaises(ValueError):b.write('mission','mission.external','new',self.clock(),'operator')
        with self.assertRaises(ValueError):Blackboard(dict(large=typed('string','x'*17000)),self.clock())

