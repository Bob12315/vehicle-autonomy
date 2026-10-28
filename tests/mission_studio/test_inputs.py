import time,unittest
from tests.visualization import test_http as legacy
from vehicle_autonomy.engine.mission.blackboard import Blackboard
from vehicle_autonomy.engine.mission.studio_graph import binding_schema


class ExternalInputTests(unittest.TestCase):
    def setUp(self):
        self.h=legacy.HttpTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
    def proposal(self,**kw):
        p=self.h.proposal(**kw);code,value,_=self.h.c.call('/api/visualization/candidates',p);self.assertEqual(code,200,value)
        return p,dict(source='external',provider='navigation_goal',id=p['id'],path='position.x',frame='odom',max_age_s=30)
    def test_tool_import_is_readonly_original_age_and_grants_no_authority(self):
        p,binding=self.proposal();lab=self.h.h.lab;now=lab.clock()
        board=Blackboard({},now,external=lambda b,t:lab.visualization_goals.read_input('rover',b,t))
        value,first=board.read('mission',binding,now);value,second=board.read('mission',binding,lab.clock())
        self.assertEqual(value,1.);self.assertEqual(first.observed_at,second.observed_at);self.assertEqual(first.frame,'odom')
        code,data,_=self.h.c.call('/api/studio-b/inputs/goals',{'target':'rover'});self.assertEqual(code,200,data)
        self.assertEqual(data['result']['goals'][0]['id'],p['id']);self.assertFalse(lab.runtime.views());self.assertFalse(lab.operator_controls.records)
        with self.assertRaises(ValueError):binding_schema(dict(binding,max_age_s=60),{}, {})
    def test_expiration_epoch_and_unqualified_map_are_rejected(self):
        _,binding=self.proposal();lab=self.h.h.lab
        self.h.h.drivers['rover'].session='reconnected'
        with self.assertRaises(ValueError):lab.visualization_goals.read_input('rover',binding,lab.clock())
        self.h.h.drivers['rover'].session='fixture-session';lab.visualization_goals.clock=lambda:time.monotonic()+31
        with self.assertRaises(ValueError):lab.visualization_goals.read_input('rover',binding,lab.clock())
        self.assertFalse(lab.runtime.views())
