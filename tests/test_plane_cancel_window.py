"""The cancellation oracle must prove interception, not trust configuration."""
from copy import deepcopy
import unittest

from pymavlink.dialects.v20 import ardupilotmega as mav
from tests.mavlink_fixture import pack
from tests.simulation.faults import TcpFaultProxy
from tests.simulation.plane_cancel_window import assert_ack_intercepted


class PlaneCancelAckEvidenceTests(unittest.TestCase):
    def setUp(self):
        sender=mav.MAVLink(None,srcSystem=1,srcComponent=1)
        raw=pack(sender.command_ack_encode(176,0,target_system=250,target_component=191),sender)
        self.frame=dict(host_ns=20,epoch=1,**TcpFaultProxy.frame_metadata(raw))
        self.rx=dict(self.frame,direction='rx',filter_dropped=True)
        self.discard=dict(self.frame,direction='rx_discard',cause='filter')

    def test_actual_discard_and_no_delivery_are_required(self):
        result=assert_ack_intercepted([self.rx,self.discard],[],since_ns=10)
        self.assertTrue(result['passed'])
        self.assertEqual((result['received'],result['discarded'],result['forwarded'],result['application_received']),
                         (1,1,0,0))

    def test_silent_noop_missing_or_wrong_discard_cannot_pass(self):
        wrong=deepcopy(self.discard);wrong['raw_hex']='not-the-received-frame'
        old=deepcopy(self.discard);old['epoch']=0
        cases=[([],[]),([self.rx],[]),([dict(self.rx,filter_dropped=False),self.discard],[]),
               ([self.rx,wrong],[]),([self.rx,old],[]),
               ([dict(self.rx,host_ns=1),dict(self.discard,host_ns=1)],[])]
        for records,app in cases:
            with self.subTest(records=records):
                with self.assertRaises(AssertionError):
                    assert_ack_intercepted(records,app,since_ns=10)

    def test_forwarded_or_application_received_ack_fails_even_with_discard_log(self):
        for forwarded,app in (([dict(self.frame,direction='rx_forward')],[]),([],[self.frame])):
            with self.subTest(forwarded=bool(forwarded),application_received=bool(app)):
                with self.assertRaisesRegex(AssertionError,'forwarded or received'):
                    assert_ack_intercepted([self.rx,self.discard,*forwarded],app,since_ns=10)

    def test_cancel_window_clears_queued_takeoff_without_relabelling_transmitted_command(self):
        from tests import test_plane_control
        from vehicle_autonomy.contracts.effects.vehicle import ModeEffect
        f=test_plane_control.PlaneControlTests();f.setUp()
        try:
            f._transmit_takeoff_on_stationary_ground()
            self.assertIsNone(f.runtime.submit_effect(ModeEffect('TAKEOFF'),effect_id='queued').reason)
            self.assertEqual(f.runtime.effect_status('queued')['phase'],'ACCEPTED')
            state=f.runtime.world_snapshot().vehicle;port=f.runtime._port
            self.assertEqual(f.runtime.end_run(),{'fixed-wing-flight':'UNCONFIRMED'})
            self.assertEqual(f.runtime.effect_status('takeoff-exit')['phase'],'UNKNOWN')
            self.assertEqual(f.runtime.effect_status('queued')['phase'],'CANCELLED')
            self.assertNotIn(f.runtime._effects['queued'],port._queue)
            self.assertEqual(f.runtime.world_snapshot().vehicle,state)
            self.assertEqual(len(f.transport.writes),1)
        finally:f.tearDown()
