"""Deterministic restart provenance and persistence fault boundaries."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests import test_basic_actions
from tests.action_system.test_runtime import Clock,Parameters
from tests.mission_graph import test_service as service_fixture
from tests.mission_graph.test_manual_input import InputFactory
from vehicle_autonomy.app.bootstrap.mission_recovery import reconstruct,retired_simulation
from vehicle_autonomy.contracts.action import ActionKind,ActionResource
from vehicle_autonomy.contracts.decision import ActionSpec
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.mission import BlackboardValue,Truth
from vehicle_autonomy.world.model.mission_inputs import evaluate


class RecoveryTests(unittest.TestCase):
    def test_result_nested_wrong_clock_quality_and_frame_remain_unknown(self):
        clock=Clock();now=clock()
        e=dict(op='eq',source='blackboard',path='out.source.value',value=True,frame='odom')
        for field in [dict(captured_at=to_json_value(replace(now,clock_domain_id='other')),value=True,frame_id='odom'),
            dict(captured_at=to_json_value(now),quality='INVALID',value=True,frame_id='odom'),
            dict(captured_at=to_json_value(now),value=True,frame_id='map'),
            dict(captured_at=to_json_value(replace(now,monotonic_ns=now.monotonic_ns+1)),value=True,frame_id='odom')]:
            bb={'out':BlackboardValue({'source':field},now,3_000_000_000)}
            self.assertIs(evaluate(e,None,bb,now),Truth.UNKNOWN)
    def test_read_only_reconstruction_rejects_no_owner_and_different_live_provider(self):
        with self.assertRaises(ValueError):reconstruct(SimpleNamespace(),[],Clock()())
        with patch('vehicle_autonomy.app.bootstrap.mission_recovery.deployment_identity',return_value={'epoch':'new'}):
            with self.assertRaises(ValueError):reconstruct(SimpleNamespace(),[{'epoch':'old'}],Clock()())
    def test_no_reconstruction_from_pid_death_or_missing_manifest_alone(self):
        self.assertFalse(retired_simulation(None))
        self.assertFalse(retired_simulation({'path':'/nonexistent/manifest.json','directory':[0,0]}))


class JournalFailureTests(unittest.TestCase):
    setUp=service_fixture.ServiceTests.setUp
    close_server=service_fixture.ServiceTests.close_server
    api=service_fixture.ServiceTests.api
    def test_journal_exception_fences_but_does_not_suppress_exit_ticks(self):
        import time
        self.registry.register_typed(ActionSpec('Drive',Parameters,kind=ActionKind.CONTINUOUS,effect_types=(ArmEffect,),
            resources=(ActionResource('vehicle.motion'),),external_lifecycle='typed_only'),InputFactory())
        v=self.lab.handle('manual.start',dict(name='Drive',target='v',parameters={},allow_send=True))
        end=time.monotonic()+2
        while time.monotonic()<end and not self.driver.writes:time.sleep(.01)
        self.assertEqual(len(self.driver.writes),1)
        with patch.object(self.lab.journal.record,'write',side_effect=OSError('injected durable failure')):
            # Force a new checkpoint, then exercise the owner loop after failure.
            a=self.lab.runtime.view(v['action']['id'])
            self.lab.runtime.update_input(a['id'],{'count':3},sequence=1,expected_deadline_ns=a['input_deadline_ns'])
            end=time.monotonic()+2
            while time.monotonic()<end:
                current=self.lab.runtime.view(a['id'])
                if self.lab.control_fault and current['state']=='CANCELLED':break
                time.sleep(.02)
            self.assertIsNotNone(self.lab.control_fault)
            self.assertEqual(current['state'],'CANCELLED')
            self.assertTrue(current['safety']['release_safe']);self.assertEqual(len(self.driver.writes),1)
            with self.assertRaises(ValueError):self.lab.handle('manual.start',dict(name='Drive',target='v',parameters={},allow_send=True))
    def test_decimal_input_ticket_preserves_large_monotonic_time(self):
        import time
        from datetime import datetime,timezone
        from vehicle_autonomy.contracts.core.time import TimePoint
        self.registry.register_typed(ActionSpec('Drive',Parameters,kind=ActionKind.CONTINUOUS,effect_types=(ArmEffect,),
            resources=(ActionResource('vehicle.motion'),),external_lifecycle='typed_only'),InputFactory())
        with self.lab._control_lock:
            clock=Clock();clock.ns=2**54+123
            self.lab.clock=clock;self.lab.runtime.clock=clock;self.lab.runtime._last_now=None
            # The factory requires no observation; this tests the JSON ticket boundary only.
            v=self.lab.handle('manual.start',dict(name='Drive',target='v',parameters={},allow_send=True))
            self.lab.runtime.tick();a=self.lab.runtime.view(v['action']['id'])
            self.assertEqual(a['input_ticket'],str(a['input_deadline_ns']))
        code,data=self.api('/api/manual/update',dict(session_id=v['session']['id'],sequence=1,deadline_ns=a['input_ticket'],parameters={'count':3}))
        self.assertEqual(code,200);self.assertEqual(data['result']['input_sequence'],1)
        for bad in ('1e18','-1','not-a-ticket'):
            clock.advance(.06)
            code,data=self.api('/api/manual/update',dict(session_id=v['session']['id'],sequence=2,deadline_ns=bad,parameters={}))
            self.assertEqual(code,409);self.assertIn('invalid input deadline ticket',data['error'])

if __name__=='__main__':unittest.main()
