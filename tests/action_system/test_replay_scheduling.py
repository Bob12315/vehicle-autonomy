"""A fast packet stream must not shorten the existing Plane command deadline."""
from threading import Lock
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from tests.simulation.plane_regressions import _wrap_replay_evidence


class ReplaySchedulingTests(unittest.TestCase):
    def run_case(self, *, false_completion=False, accept_ack=False, extra_write=False):
        clock=[0.0];pending=[];scheduled=[];writes=[b'actual-disarm']
        rejected={'replay':0};ack_evidence={}
        proxy=NS(_lock=Lock(),records=[])
        def replay(raw):
            scheduled.append(raw);pending.append((clock[0]+.2,raw))
        proxy.replay_rx=replay
        def status(_):
            return {'phase':'COMPLETED' if false_completion and clock[0]>=2.7
                else 'UNKNOWN' if clock[0]>=5 else 'TRANSMITTED'}
        runtime=NS(_receive_signing=NS(rejected=rejected),_effects={'plane-wrap-disarm':'command'},
            _port=NS(ack_evidence=ack_evidence),effect_status=status,
            world_snapshot=lambda:NS(vehicle=NS(operation=NS(armed=True))))
        def cycle():
            clock[0]+=.1
            proxy.records.append({'direction':'rx','sequence':(round(clock[0]*10)*32)%256})
            for item in list(pending):
                if clock[0]>=item[0]:
                    rejected['replay']+=1;pending.remove(item)
            if accept_ack:ack_evidence['command']={}
            if extra_write and len(writes)==1:writes.append(b'unexpected')
        with patch('tests.simulation.plane_regressions.time.monotonic',side_effect=lambda:clock[0]):
            result=_wrap_replay_evidence(runtime,proxy,cycle,b'old-ack',[b'old-hb-1',b'old-hb-2'],writes,0)
        return result,clock[0],scheduled

    def test_fast_wraps_wait_for_actual_timeout_and_received_replays(self):
        result,elapsed,scheduled=self.run_case()
        self.assertGreaterEqual(elapsed,5)
        self.assertLess(elapsed,5.2)
        self.assertEqual(result['status']['phase'],'UNKNOWN')
        self.assertEqual(result['wraps'],3)
        self.assertEqual(result['replay_rejections'],9)
        self.assertEqual(scheduled,[b'old-ack',b'old-hb-1',b'old-hb-2']*3)
        self.assertEqual(result['writer_calls'],1)

    def test_false_completion_is_still_rejected(self):
        with self.assertRaisesRegex(AssertionError,'changed command or World'):
            self.run_case(false_completion=True)

    def test_accepted_old_ack_and_extra_writer_still_fail(self):
        for kwargs in ({'accept_ack':True},{'extra_write':True}):
            with self.subTest(kwargs=kwargs),self.assertRaisesRegex(AssertionError,'evidence incomplete'):
                self.run_case(**kwargs)
