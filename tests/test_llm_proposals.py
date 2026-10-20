import json
import unittest

from intelligence.proposals import MissionProposal, LlmAdapter
from application.proposals import ProposalService


class Application:
    def __init__(self):
        self.state = {'profile':'rover_sim','state':'READY','session_id':'one',
                      'world_version':{'generation':'one','revision':1},'environment':{'id':'test'}}
        self.starts=[]
    def handle(self, command, payload):
        if command=='status':return self.state
        if command in ('start','start_checked'):
            if command=='start_checked' and payload['expected_session']!=self.state['session_id']:
                raise ValueError('session changed')
            self.starts.append(payload);return {'started':True}
        raise ValueError(command)


class Adapter:
    def propose(self,text,registered):
        return MissionProposal.parse(json.dumps({'decision':'propose','mission':registered[0],'reason':'test'}),registered)


class LlmTests(unittest.TestCase):
    def test_strict_schema_unknown_mission_and_executable_payload_rejected(self):
        for value in ({'decision':'propose','mission':'arm','reason':'x'},
                      {'decision':'propose','mission':'basic_route','reason':'x','python':'print(1)'},
                      {'decision':'clarify','mission':'basic_route','reason':'x'},
                      {'decision':'propose','mission':None,'reason':'x'}):
            with self.assertRaises(ValueError):MissionProposal.parse(json.dumps(value),['basic_route'])
        self.assertEqual(MissionProposal.parse('{"decision":"reject","mission":null,"reason":"unsafe"}',[]).decision,'reject')

    def test_human_approval_replay_and_expiry(self):
        app=Application();clock=[0];service=ProposalService(Adapter(),app,['basic_route'],clock=lambda:clock[0])
        result=service.propose('route');self.assertEqual(app.starts,[])
        with self.assertRaises(ValueError):service.approve(result['id'],False)
        service.approve(result['id'],True);self.assertEqual(len(app.starts),1)
        with self.assertRaises(ValueError):service.approve(result['id'],True)
        result=service.propose('route');clock[0]=61
        with self.assertRaises(ValueError):service.approve(result['id'],True)

    def test_changed_session_and_real_hardware_never_execute(self):
        app=Application();service=ProposalService(Adapter(),app,['basic_route'])
        result=service.propose('route');app.state['session_id']='two'
        with self.assertRaises(ValueError):service.approve(result['id'],True)
        app.state['profile']='onboard_readonly';app.state['mode']='hardware_readonly'
        result=service.propose('route')
        with self.assertRaises(ValueError):service.approve(result['id'],True)
        self.assertEqual(app.starts,[])

    def test_llm_failure_cannot_start_or_cancel_navigation(self):
        class Offline:
            def propose(self,*args):raise TimeoutError('offline')
        app=Application();service=ProposalService(Offline(),app,['basic_route'])
        with self.assertRaises(TimeoutError):service.propose('route')
        self.assertEqual(app.starts,[])
        self.assertEqual(app.state['state'],'READY')
