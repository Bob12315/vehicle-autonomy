"""Private worker failure and admission boundaries; no native simulator claim."""
from concurrent.futures import Future
from pathlib import Path
from threading import Event,RLock
from types import SimpleNamespace
import unittest

from vehicle_autonomy.app.simulation.driver_worker import ProcessVehicleDriver
from vehicle_autonomy.contracts.action_ports import ActionAdmissionRejected


class PipeFixture:
    def __init__(self,messages=()):self.messages=list(messages);self.sent=[]
    def recv(self):
        if not self.messages:raise EOFError()
        return self.messages.pop(0)
    def send(self,message):self.sent.append(message)


class WorkerProxyContracts(unittest.TestCase):
    def proxy(self,messages=()):
        driver=ProcessVehicleDriver.__new__(ProcessVehicleDriver)
        driver._lock=RLock();driver._send_lock=RLock();driver._retiring=Event();driver._ready=Event()
        driver._closed=False;driver._expected_close=False;driver._pending={};driver._error=None
        driver._info=dict(connected=True,system_send=True,action_send=True,lease_active=True,fault=None)
        driver._world=None
        driver._effects={'old-action':('immutable-evidence',)};driver._feedback={};driver._guards={}
        driver.connection=PipeFixture(messages);driver.process=SimpleNamespace(poll=lambda:None)
        return driver

    def test_retirement_rejects_before_private_pipe_but_allows_exit(self):
        d=self.proxy();d._retiring.set()
        with self.assertRaises(ActionAdmissionRejected):d.open_scope('new',allow_send=True).result()
        self.assertEqual(d.connection.sent,[])
        d.begin_exit('existing')
        self.assertEqual(d.connection.sent[-1][1],'begin_exit')

    def test_eof_fails_all_pending_scopes_and_exposes_no_live_send(self):
        d=self.proxy();future=d._call('open_scope','new')
        d._read()
        with self.assertRaisesRegex(RuntimeError,'link lost'):future.result()
        self.assertFalse(d.info()['connected']);self.assertFalse(d.info()['system_send'])
        self.assertFalse(d.info()['action_send']);self.assertFalse(d.info()['lease_active'])
        self.assertEqual(d.effect_results('old-action'),('immutable-evidence',))
        self.assertTrue(d._ready.is_set())

    def test_pending_budget_rejects_without_sending_one_more_request(self):
        d=self.proxy();d._pending={str(i):Future() for i in range(128)}
        with self.assertRaisesRegex(RuntimeError,'bounded'):d._call('emit','new').result()
        self.assertEqual(d.connection.sent,[])
        self.assertEqual(len(d._pending),128)

    def test_typed_admission_rejection_survives_worker_response(self):
        d=self.proxy();future=d._call('open_scope','new')
        identifier=d.connection.sent[0][0]
        d.connection.messages=[('result',identifier,False,ActionAdmissionRejected('no new authority'))]
        d._read()
        with self.assertRaisesRegex(ActionAdmissionRejected,'no new authority'):future.result()

    def test_dead_process_cannot_queue_scope_even_if_cached_state_was_valid(self):
        d=self.proxy();d.process=SimpleNamespace(poll=lambda:17)
        with self.assertRaisesRegex(RuntimeError,'unavailable'):d._call('open_scope','new').result()
        self.assertEqual(d.connection.sent,[])


if __name__=='__main__':unittest.main()
