"""Regression for the independent Phase 3 exit and ROS admission failures."""
from concurrent.futures import Future
from contextlib import redirect_stdout
import io
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from vehicle_autonomy.actions.common.standard import Empty
from vehicle_autonomy.actions.external.job import ExternalFactory
from vehicle_autonomy.actions.external import ros_worker
from vehicle_autonomy.app.bootstrap.external_actions import ExternalActionDriver,register_external
from vehicle_autonomy.contracts.action import ActionKind,ActionResource,ActionSafety
from vehicle_autonomy.contracts.action_ports import ActionAdmissionRejected
from vehicle_autonomy.contracts.decision import ActionSpec,ActionDecision,ActionOutcome,ExitDecision
from vehicle_autonomy.engine.action.registry import ActionRegistry
from vehicle_autonomy.engine.action.runtime import ActionRuntime
from tests.action_system.test_runtime import Clock
from tests.action_system.test_persistent_resources import initialize_test_store,isolated_test_registry


class ExitBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.state=tempfile.TemporaryDirectory();self.addCleanup(self.state.cleanup)
        isolated_test_registry(self,Path(self.state.name)/'provider-registry')
        initialize_test_store(Path(self.state.name)/'resources')
    def driver(self):return ExternalActionDriver(state_dir=Path(self.state.name)/'resources')
    def test_exit_exception_remains_quarantined_after_many_ticks(self):
        active=[]
        class Instance:
            def tick(self,_):return ActionDecision(ActionOutcome.RUNNING)
            def exit(self,*_):raise RuntimeError('remote cancellation response lost')
        class Factory:
            def start(self,*_):active.append(Instance());return active[-1]
        reg=ActionRegistry();reg.register_typed(ActionSpec('opaque',Empty,kind=ActionKind.CONTINUOUS,
            resources=(ActionResource('ai.inference'),)),Factory())
        rt=ActionRuntime(reg,{'external':self.driver()},clock=Clock())
        a=rt.submit('opaque','external');rt.tick();rt.cancel(a['id'])
        for _ in range(8):rt.tick()
        self.assertEqual(rt.view(a['id'])['state'],'UNKNOWN')
        self.assertFalse(rt.view(a['id'])['safety']['release_safe'])
        self.assertTrue(rt.resource_view())
        self.assertEqual(rt.submit('opaque','external')['state'],'REJECTED')
        self.assertEqual(len(active),1)

    def test_hung_external_exit_cannot_be_cleared_by_empty_vehicle_guard(self):
        jobs=[]
        class Job:
            active=True
            def poll(self):return {'state':'RUNNING'}
            def cancel(self):pass
            def close(self):pass
        def create(_):jobs.append(Job());return jobs[-1]
        reg=ActionRegistry();register_external(reg,'hung',create,continuous=True)
        clock=Clock();rt=ActionRuntime(reg,{'external':self.driver()},clock=clock)
        a=rt.submit('hung','external');rt.tick();rt.cancel(a['id']);rt.tick()
        clock.advance(9)
        for _ in range(8):rt.tick()
        self.assertEqual(rt.view(a['id'])['state'],'UNKNOWN')
        self.assertFalse(rt.view(a['id'])['safety']['release_safe'])
        self.assertTrue(rt.resource_view())
        b=rt.submit('hung','external',wait_timeout_s=1);clock.advance(2);rt.tick()
        self.assertEqual(rt.view(b['id'])['state'],'TIMED_OUT')
        self.assertEqual(len(jobs),1)

    def test_explicit_no_side_effect_rejection_releases_and_valid_action_can_follow(self):
        reg=ActionRegistry();register_external(reg,'denied',lambda _:(_ for _ in ()).throw(ActionAdmissionRejected('no request submitted')))
        rt=ActionRuntime(reg,{'external':self.driver()},clock=Clock())
        a=rt.submit('denied','external')
        for _ in range(5):rt.tick()
        self.assertEqual(rt.view(a['id'])['state'],'FAILED')
        self.assertTrue(rt.view(a['id'])['safety']['release_safe']);self.assertEqual(rt.resource_view(),[])

    def test_query_exit_exception_does_not_quarantine_an_external_effect_resource(self):
        class Query:
            def start(self,*_):return self
            def tick(self,_):return ActionDecision(ActionOutcome.SUCCEEDED,result={})
            def exit(self,*_):raise RuntimeError('read-only cleanup failed')
        reg=ActionRegistry();reg.register_typed(ActionSpec('read',Empty,kind=ActionKind.QUERY,
            resources=(ActionResource('state'),)),Query())
        rt=ActionRuntime(reg,{'external':self.driver()},clock=Clock());a=rt.submit('read','external')
        for _ in range(5):rt.tick()
        self.assertEqual(rt.view(a['id'])['state'],'FAILED');self.assertEqual(rt.resource_view(),[])


def worker_result(*,service,submitted_failure=True,rejected=False,unavailable=False):
    requests=[]
    class Client:
        def __init__(self,*a,**kw):pass
        def wait_for_service(self,**kw):return not unavailable
        def wait_for_server(self,**kw):return not unavailable
        def request(self):
            requests.append('submitted');future=Future()
            if submitted_failure:future.set_exception(RuntimeError('submitted response lost'))
            elif rejected:future.set_result(NS(accepted=False))
            else:future.set_result(NS(success=True,message='actual result'))
            return future
        def call_async(self,*a,**kw):return self.request()
        def send_goal_async(self,*a,**kw):return self.request()
        def destroy(self):pass
    class Node:
        def create_client(self,*a):return Client()
        def destroy_node(self):pass
    class Goal:
        def __init__(self):self.time=NS(sec=0,nanosec=0)
    modules={'rclpy':NS(init=lambda:None,create_node=lambda _:Node(),spin_once=lambda *a,**kw:None,shutdown=lambda:None),
        'rclpy.action':NS(ActionClient=Client),'nav2_msgs.action':NS(Wait=NS(Goal=Goal)),
        'std_srvs.srv':NS(Trigger=NS(Request=object))}
    buffer=io.StringIO()
    with patch.dict(sys.modules,modules),patch.object(sys,'stdin',io.StringIO('')),redirect_stdout(buffer),patch.object(sys,'argv',
            ['worker','--name','/vaf_phase3_boundary/request',*(['--service'] if service else [])]):
        ros_worker.main()
    return json.loads(buffer.getvalue().splitlines()[-1]),requests


class RosAdmissionTests(unittest.TestCase):
    def test_submitted_service_and_action_future_failure_are_unknown(self):
        for service in (True,False):
            with self.subTest(service=service):
                result,requests=worker_result(service=service)
                self.assertEqual(len(requests),1)
                self.assertEqual(result['state'],'UNKNOWN')

    def test_unavailable_before_submission_and_explicit_rejection_remain_failed(self):
        for service in (True,False):
            result,requests=worker_result(service=service,unavailable=True)
            self.assertEqual(result['state'],'FAILED');self.assertEqual(requests,[])
        result,requests=worker_result(service=False,submitted_failure=False,rejected=True)
        self.assertEqual(result['state'],'FAILED');self.assertEqual(len(requests),1)

    def test_normal_service_result_still_succeeds(self):
        result,requests=worker_result(service=True,submitted_failure=False)
        self.assertEqual(result['state'],'SUCCEEDED');self.assertEqual(len(requests),1)
