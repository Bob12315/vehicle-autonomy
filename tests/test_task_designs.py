"""Design admission, bounded sequencing and sole-writer lifecycle assertions."""
import json
import threading
import unittest

from application.design_proposals import DesignProposalService
from application.runtime_service import RuntimeService
from intelligence.designs import MissionDesign
from tests.test_application_runtime import ApplicationRuntimeTests


def document(*missions, decision='propose'):
    return dict(schema=1, decision=decision, title='Test design', reason='Finite test',
                steps=[{'mission':m} for m in missions])


class SchemaTests(unittest.TestCase):
    def test_exact_bounded_non_executable_schema(self):
        good=document('disarmed_mode','disarmed_mode')
        parsed=MissionDesign.parse(json.dumps(good),['disarmed_mode'])
        self.assertEqual(parsed.document(),good)
        self.assertEqual(parsed.sha256,MissionDesign.parse(json.dumps(good,indent=2),['disarmed_mode']).sha256)
        for bad in [document('raw_pwm'),document('designed:other'),document(*(['disarmed_mode']*9)),
                    document(),document('disarmed_mode',decision='reject'),
                    {**good,'python':'arbitrary()'}, {**good,'schema':True},
                    {**good,'steps':[{'mission':'disarmed_mode','x':1}]},
                    {**good,'steps':[{'mission':[]}]}]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                MissionDesign.parse(json.dumps(bad),['disarmed_mode','designed:other'])
        for bad in ['{"schema":1,"schema":1}', '{"schema":NaN}', '['*1500+']'*1500]:
            with self.assertRaises(ValueError):MissionDesign.parse(bad,[])
        self.assertEqual(MissionDesign.parse(json.dumps(document(decision='clarify')),[]).missions,())


class DesignRuntimeTests(ApplicationRuntimeTests):
    def bind(self):
        self.app_cycle(self.heartbeat()+self.state_messages())
        return self.app.design_catalog()

    def start_design(self,*missions):
        catalog=self.bind()
        return self.app.start_design_checked(document(*missions),catalog['context'],catalog['session_id'])

    def telemetry(self,ack=False):
        self.app_cycle((self.sender.command_ack_encode(176,0).pack(self.sender) if ack else b'')
                       +self.heartbeat(mode=4)+self.state_messages())

    def test_two_steps_distinct_ids_ack_boundary_and_release(self):
        self.ready()
        result=self.start_design('disarmed_mode','disarmed_mode')
        self.assertEqual(self.transports[-1].writes,[])
        with self.assertRaisesRegex(ValueError,'designed task'):self.app.start_mission('disarmed_mode')
        # Fresh telemetry and multiple distinct samples, then original Action -> Effect writer.
        for _ in range(9):self.telemetry()
        self.assertEqual(len(self.transports[-1].writes),1)
        self.assertEqual(self.app.get_status()['task']['task_id'],result['task_id'])
        # No ACK means no next step even with matching mode telemetry.
        for _ in range(4):self.telemetry()
        self.assertEqual(len(self.transports[-1].writes),1)
        for _ in range(30):self.telemetry(ack=True)
        final=self.app.get_status()['task']
        self.assertEqual(final['status'],'SUCCEEDED',final)
        ids=[r['task_id'] for r in final['completed']]
        self.assertEqual(len(set(ids)),2)
        self.assertEqual(len(self.transports[-1].writes),2)
        self.assertEqual(final['stop_evidence'],'SIMULATION_TELEMETRY_DISARMED_STATIONARY')
        self.assertFalse(self.runtime.authority.system_send)
        self.assertIsNone(self.runtime.authority.lease)

    def test_cancel_fences_pending_steps_and_stale_telemetry_is_not_stop_proof(self):
        self.ready();self.start_design('disarmed_mode','disarmed_mode')
        self.app.cancel_mission()
        for _ in range(110):self.app_cycle()
        final=self.app.get_status()['task']
        self.assertEqual(final['status'],'FAILED',final)
        self.assertEqual(final['stop_evidence'],'UNCONFIRMED')
        self.assertEqual(self.transports[-1].writes,[])

    def test_cancel_active_child_stops_sequence_and_retains_child_result(self):
        self.ready();self.start_design('disarmed_mode','disarmed_mode')
        for _ in range(8):self.telemetry()
        self.app.cancel_mission()
        for _ in range(20):self.telemetry(ack=True)
        final=self.app.get_status()['task']
        self.assertEqual(final['status'],'CANCELLED',final)
        self.assertEqual(len(final['completed']),1)
        self.assertEqual(len(self.transports[-1].writes),1)
        self.assertFalse(self.runtime.authority.system_send)

    def test_context_change_readonly_hardware_and_old_session_cannot_start(self):
        self.ready(False);catalog=self.bind()
        for context,session in [('wrong',catalog['session_id']),(catalog['context'],'old')]:
            with self.assertRaises(ValueError):self.app.start_design_checked(document('disarmed_mode'),context,session)
        check=self.app.design_preflight(document('disarmed_mode'),catalog['context'])
        self.assertIn('simulation_SEND_not_authorized',check['reasons'])
        with self.assertRaises(ValueError):self.app.start_design_checked(document('disarmed_mode'),catalog['context'],catalog['session_id'])
        self.app.profile_name='hardware_readonly'
        with self.assertRaises(ValueError):self.app.design_catalog()
        self.assertEqual(self.transports[-1].writes,[])

    def test_stale_boundary_cannot_pass_preflight(self):
        self.ready();catalog=self.bind()
        self.clock.ns+=600_000_000
        check=self.app.design_preflight(document('disarmed_mode'),catalog['context'])
        self.assertIn('localization_or_twist_stale',check['reasons'])
        self.assertEqual(self.transports[-1].writes,[])

    def test_total_deadline_cannot_launch_next_step(self):
        self.ready()
        self.start_design('disarmed_mode','disarmed_mode')
        self.app.design_task.deadline_ns=self.clock.ns
        for _ in range(8):self.telemetry()
        result=self.app.get_status()['task']
        self.assertEqual(result['status'],'FAILED',result)
        self.assertIn('deadline',result['error'])
        self.assertEqual(self.transports[-1].writes,[])

    def test_context_change_invalidates_running_design_without_automatic_restart(self):
        self.ready();self.start_design('disarmed_mode','disarmed_mode')
        self.app.design_task.context='old_context'
        for _ in range(8):self.telemetry()
        result=self.app.get_status()['task']
        self.assertEqual(result['status'],'FAILED',result)
        self.assertIn('context_changed',result['error'])
        self.assertEqual(self.transports[-1].writes,[])

    def test_disconnect_cannot_resume_design_or_reuse_old_authority(self):
        self.ready();self.start_design('disarmed_mode','disarmed_mode')
        for _ in range(8):self.telemetry()
        self.transports[-1].disconnected=True;self.app_cycle()
        for _ in range(110):self.telemetry()
        final=self.app.get_status()['task']
        self.assertEqual(final['status'],'FAILED',final)
        self.assertLessEqual(len(final['completed']),1)
        self.assertFalse(self.runtime.authority.system_send)
        self.assertIsNone(self.runtime.authority.lease)


class ApprovalTests(unittest.TestCase):
    def test_blocked_design_inference_does_not_hold_operator_cancel_lock(self):
        from tempfile import TemporaryDirectory
        from application.operator_service import OperatorService
        entered,release,finished=threading.Event(),threading.Event(),threading.Event()
        class App:
            def handle(self,op,p):
                if op=='design_catalog':return dict(context='ctx',session_id='s',capabilities={})
                if op=='cancel':return {'cancelled':True}
                raise ValueError(op)
        class Model:
            def design(self,*args):
                entered.set();release.wait(timeout=3)
                return MissionDesign.parse(json.dumps(document(decision='clarify')),[])
        with TemporaryDirectory() as directory:
            service=OperatorService(App(),directory,llm=Model())
            worker=threading.Thread(target=lambda:service.handle('design',{'text':'wait'}));worker.start()
            try:
                self.assertTrue(entered.wait(timeout=1))
                cancel=threading.Thread(target=lambda:(service.handle('cancel',{}),finished.set()));cancel.start()
                self.assertTrue(finished.wait(timeout=.5),'design inference held cancel lock')
                cancel.join(timeout=1)
            finally:release.set();worker.join(timeout=2)

    def test_approval_ttl_replay_and_curated_capability_bound(self):
        class App:
            def __init__(self):self.starts=[]
            def handle(self,op,p):
                if op=='design_catalog':return dict(context='ctx',session_id='s',capabilities={'disarmed_mode':{},'basic_route':{}})
                if op=='design_preflight':return {'eligible':True}
                self.starts.append(p);return {'task_id':'one'}
        class Model:
            def design(self,text,capabilities):
                self.assert_catalog=capabilities
                return MissionDesign.parse(json.dumps(document('disarmed_mode')),capabilities)
        app=App();model=Model();clock=[0]
        service=DesignProposalService(model,app,['disarmed_mode'],clock=lambda:clock[0])
        proposal=service.propose('HOLD twice')
        self.assertEqual(set(model.assert_catalog),{'disarmed_mode'});self.assertEqual(app.starts,[])
        with self.assertRaises(ValueError):service.approve(proposal['id'],False)
        service.approve(proposal['id'],True)
        with self.assertRaises(ValueError):service.approve(proposal['id'],True)
        proposal=service.propose('HOLD');clock[0]=60
        with self.assertRaises(ValueError):service.approve(proposal['id'],True)
        self.assertEqual(len(app.starts),1)

    def test_ipc_rejects_fields_and_unavailable_hardware_composition(self):
        class Hardware:pass
        service=RuntimeService(Hardware())
        for op in ('design_catalog','design_preflight','start_design_checked'):
            with self.assertRaises(ValueError):service.handle(op,{})
