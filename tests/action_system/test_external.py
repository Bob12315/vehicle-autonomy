"""Native/real local HTTP job contracts; actual ROS is a separate DDS run."""
from dataclasses import asdict
from threading import Thread
import time
import unittest

from vehicle_autonomy.actions.external.clients import ApiJob
from vehicle_autonomy.app.bootstrap.external_actions import ExternalActionDriver,register_external
from vehicle_autonomy.app.web.action_lab import ActionLab
from vehicle_autonomy.engine.action.registry import ActionRegistry
from tests.simulation.external_actions import timer,JobServer


class ExternalTests(unittest.TestCase):
    def setUp(self):
        self.server=JobServer();self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        registry=ActionRegistry();register_external(registry,'native',timer)
        register_external(registry,'api',lambda p:ApiJob(f'http://127.0.0.1:{self.server.server_address[1]}',asdict(p)))
        self.lab=ActionLab({'external':ExternalActionDriver()},registry=registry)
    def tearDown(self):
        self.lab.close();self.server.shutdown();self.server.server_close();self.thread.join(2)
        for job in self.server.jobs.values():job.cancel();job.close()
    def wait(self,a):
        until=time.monotonic()+4
        while time.monotonic()<until:
            a=self.lab.runtime.view(a['id'])
            if a['state'] in ('SUCCEEDED','FAILED','CANCELLED','TIMED_OUT','UNKNOWN'):return a
            time.sleep(.02)
        self.fail('external job did not terminate')
    def test_native_and_http_feedback_real_completion_error_and_cancel(self):
        for name in ('native','api'):
            a=self.lab.runtime.submit(name,'external',{'duration_s':.2})
            value=self.wait(a);self.assertEqual(value['state'],'SUCCEEDED');self.assertTrue(value['feedback'])
            value=self.wait(self.lab.runtime.submit(name,'external',{'duration_s':.1,'behavior':'error'}))
            self.assertEqual(value['state'],'FAILED');self.assertTrue(value['safety']['release_safe'])
            a=self.lab.runtime.submit(name,'external',{'duration_s':3});time.sleep(.15);self.lab.runtime.cancel(a['id'])
            self.assertEqual(self.wait(a)['state'],'CANCELLED');self.assertEqual(self.lab.runtime.resource_view(),[])
    def test_http_timeout_cancels_actual_job_and_releases_only_after_result(self):
        a=self.lab.runtime.submit('api','external',{'duration_s':3},timeout_s=.25)
        value=self.wait(a);self.assertEqual(value['state'],'TIMED_OUT');self.assertTrue(value['safety']['release_safe'])
        self.assertTrue(self.server.jobs)
        self.assertEqual({j.poll()['state'] for j in self.server.jobs.values()},{'CANCELLED'})
    def test_unknown_response_is_quarantined_not_reported_as_failure_without_effects(self):
        self.server.shutdown();self.server.server_close()
        a=self.lab.runtime.submit('api','external',{})
        value=self.wait(a);self.assertEqual(value['state'],'UNKNOWN');self.assertFalse(value['safety']['release_safe'])
        self.assertEqual(self.lab.runtime.submit('native','external',{})['state'],'REJECTED')
    def test_cancel_cleanup_exception_cannot_release_an_external_service(self):
        calls=[]
        class Broken:
            def poll(self):return {'state':'RUNNING'}
            def cancel(self):calls.append('cancel');raise RuntimeError('cancel response lost')
            def close(self):calls.append('close');raise RuntimeError('close failed')
        register_external(self.lab.registry,'broken',lambda _:Broken())
        a=self.lab.runtime.submit('broken','external',{});time.sleep(.1);self.lab.runtime.cancel(a['id'])
        value=self.wait(a);self.assertEqual(value['state'],'UNKNOWN');self.assertFalse(value['safety']['release_safe'])
        self.assertIn('cancel',calls);self.assertIn('close',calls);self.assertTrue(self.lab.runtime.resource_view())
    def test_opaque_admission_exception_does_not_claim_no_remote_side_effect(self):
        register_external(self.lab.registry,'uncertain',lambda _:(_ for _ in ()).throw(RuntimeError('lost admission')))
        value=self.wait(self.lab.runtime.submit('uncertain','external',{}))
        self.assertEqual(value['state'],'UNKNOWN');self.assertFalse(value['safety']['release_safe'])


if __name__=='__main__':unittest.main()
