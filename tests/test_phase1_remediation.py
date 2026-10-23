"""Independent review reproductions: bytes and actual writer calls are evidence."""

from tests.mavlink_fixture import pack
from dataclasses import replace
from threading import Event, Thread
import unittest

from pymavlink.dialects.v20 import ardupilotmega as mav
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect, DisarmEffect, ModeEffect
from vehicle_autonomy.contracts.vehicle.command import CommandPhase
from vehicle_autonomy.vehicles.ardupilot.mavlink.codec import CommandLong, MavlinkCodec
from tests import test_p5_mavlink as p5
from tests.test_p5_mavlink import at, effect, world


class ReviewReproductions(unittest.TestCase):
    def setUp(self):
        self.fx = p5.P5MavlinkTests(); self.fx.setUp(); self.fx.connect()

    def submit(self, index, payload, now=101, deadline=180):
        f=self.fx; f.now_ns=now
        return f.execution.dispatch(effect(index,payload,deadline=deadline),world(),at(now)).receipt

    def test_old_arm_ack_and_disarmed_heartbeat_cannot_complete_disarm(self):
        f=self.fx
        old_unarmed=f.heartbeat()
        f.transport.incoming.append(old_unarmed);f.session.poll(at(101))
        arm=self.submit(1,ArmEffect(),102);f.now_ns=103;f.session.write_next(at(103))
        old_ack=f.ack(400)
        f.transport.incoming.append(old_ack);f.session.poll(at(104))
        # The existing implementation completes here. Fixed implementation will
        # require additional source-timed, distinct state evidence (added below).
        f.transport.incoming.append(f.heartbeat(armed=True));f.session.poll(at(105))
        self.assertEqual(f.port.status(arm.command_id).phase,CommandPhase.COMPLETED)
        disarm=self.submit(2,DisarmEffect(),106);f.now_ns=107;f.session.write_next(at(107))
        before=len(f.transport.writes)
        f.transport.incoming.append(old_ack);f.session.poll(at(108))
        f.transport.incoming.append(old_unarmed);f.session.poll(at(109))
        self.assertNotEqual(f.port.status(disarm.command_id).phase,CommandPhase.COMPLETED)
        self.assertEqual(len(f.transport.writes),before)
        self.assertTrue(f.session.snapshot().operation.armed)

    def test_expiration_while_waiting_for_lock_writes_zero(self):
        f=self.fx;receipt=self.submit(1,ArmEffect(),101,deadline=110)
        entered=Event();finished=Event();errors=[]
        def worker():
            entered.set()
            try:f.port.write_next(at(102))
            except BaseException as exc:errors.append(exc)
            finally:finished.set()
        with f.authority.lock:
            thread=Thread(target=worker);thread.start();self.assertTrue(entered.wait(1))
            f.now_ns=111
        self.assertTrue(finished.wait(2));thread.join();self.assertFalse(errors)
        self.assertEqual(f.transport.writes,[])
        self.assertEqual(f.transport.attempts,[])
        self.assertEqual(f.port.status(receipt.command_id).phase,CommandPhase.REJECTED)

    def test_guard_expiration_writes_zero(self):
        f=self.fx;receipt=self.submit(1,ArmEffect(),101,deadline=110)
        def guard(command):f.now_ns=111
        f.port._write_guard=guard;f.now_ns=102;f.port.write_next(at(102))
        self.assertEqual(f.transport.writes,[])
        self.assertEqual(f.transport.attempts,[])
        self.assertEqual(f.port.status(receipt.command_id).phase,CommandPhase.REJECTED)

    def test_guard_exception_fails_closed_and_next_valid_command_sends(self):
        f=self.fx;receipt=self.submit(1,ArmEffect())
        def guard(command):raise RuntimeError('guard failed')
        f.port._write_guard=guard;f.now_ns=102
        f.port.write_next(at(102))
        self.assertEqual(f.transport.writes,[])
        self.assertEqual(f.transport.attempts,[])
        self.assertEqual(f.port.status(receipt.command_id).phase,CommandPhase.REJECTED)
        f.port._write_guard=None;fresh=self.submit(2,ArmEffect(),103)
        f.now_ns=104;f.port.write_next(at(104))
        self.assertEqual(len(f.transport.writes),1)
        self.assertEqual(f.port.status(fresh.command_id).phase,CommandPhase.TRANSMITTED)
        parsed=f.codec.feed(f.transport.writes[0])[0]
        self.assertEqual((parsed.command,parsed.param1),(400,1))

    def test_codec_sequence_advances_and_wraps(self):
        codec=MavlinkCodec(source_system=250,source_component=191,target_system=1,target_component=1)
        instruction=CommandLong(400,(1.,0.,0.,0.,0.,0.,0.))
        sequences=[codec.feed(codec.encode(instruction))[0].get_seq() for _ in range(258)]
        self.assertEqual(sequences,list(range(256))+[0,1])

    def test_one_fresh_heartbeat_is_insufficient_then_normal_disarm_completes(self):
        f=self.fx
        arm=self.submit(1,ArmEffect());f.now_ns=102;f.session.write_next(at(102))
        ack=pack(f.sender.command_ack_encode(400,0),f.sender)
        f.transport.incoming.append(ack);f.session.poll(at(103))
        def state(armed,boot):
            return (pack(f.sender.attitude_encode(boot,0,0,0,0,0,0),f.sender)
                    +pack(f.sender.heartbeat_encode(2,3,128 if armed else 0,4,4),f.sender)
                    +pack(f.sender.attitude_encode(boot+1,0,0,0,0,0,0),f.sender))
        first=state(True,100)
        f.transport.incoming.append(first);f.session.poll(at(104))
        self.assertEqual(f.port.status(arm.command_id).phase,CommandPhase.ACKNOWLEDGED)
        f.transport.incoming.append(first);f.session.poll(at(105))
        self.assertNotEqual(f.port.status(arm.command_id).phase,CommandPhase.COMPLETED)
        f.transport.incoming.append(state(True,102));f.session.poll(at(106))
        self.assertEqual(f.port.status(arm.command_id).phase,CommandPhase.COMPLETED)
        disarm=self.submit(2,DisarmEffect(),107);f.now_ns=108;f.session.write_next(at(108))
        f.transport.incoming.append(ack);f.session.poll(at(109))
        self.assertEqual(f.port.status(disarm.command_id).phase,CommandPhase.TRANSMITTED)
        f.transport.incoming.append(pack(f.sender.command_ack_encode(400,0),f.sender));f.session.poll(at(110))
        for time_ns,boot in ((111,104),(112,106)):
            f.transport.incoming.append(state(False,boot));f.session.poll(at(time_ns))
        self.assertEqual(f.port.status(disarm.command_id).phase,CommandPhase.COMPLETED)
        self.assertEqual(f.port.ack_evidence[disarm.command_id]['correlation'],'unproven_mav_cmd_only')
        self.assertEqual(len(f.transport.writes),2)
        frames=f.codec.feed(b''.join(f.transport.writes))
        self.assertEqual([(m.command,m.param1,m.get_seq()) for m in frames],[(400,1,0),(400,0,1)])

    def test_receive_wrap_reorder_duplicate_and_reboot_isolate_old_scope(self):
        f=self.fx
        # Complete one sequence cycle using timed AP packets, including 255->0.
        for index in range(270):
            raw=pack(f.sender.attitude_encode(1000+index,0,0,0,0,0,0),f.sender)
            f.transport.incoming.append(raw);f.session.poll(at(101))
        self.assertEqual(f.session.receive_rejections['out_of_order'],0)
        before=f.session._rx_ticket
        f.transport.incoming.append(raw);f.session.poll(at(101))
        self.assertEqual(f.session._rx_ticket,before)
        old_session=f.session.session_id
        f.transport.incoming.append(pack(f.sender.attitude_encode(1,0,0,0,0,0,0),f.sender))
        with self.assertRaisesRegex(ValueError,'boot clock regressed'):
            f.session.poll(at(102))
        self.assertIsNone(f.session.session_id)
        self.assertIsNone(f.session.snapshot())
        self.assertFalse(f.authority.system_send)
        self.assertIsNone(f.authority.lease)
        f.transport.incoming.append(f.heartbeat());f.session.poll(at(103))
        self.assertNotEqual(f.session.session_id,old_session)
        self.assertEqual(f.transport.writes,[])
        self.assertEqual(f.transport.attempts,[])

    def test_unqualified_source_clock_cannot_complete_from_receive_time(self):
        f=self.fx;f.session._confirmation_time_qualified=False
        receipt=self.submit(1,ArmEffect());f.now_ns=102;f.session.write_next(at(102))
        f.transport.incoming.append(pack(f.sender.command_ack_encode(400,0),f.sender));f.session.poll(at(103))
        f.transport.incoming.append(f.heartbeat(armed=True));f.session.poll(at(104))
        self.assertEqual(f.port.status(receipt.command_id).phase,CommandPhase.ACKNOWLEDGED)
        f.session.tick(at(180))
        self.assertEqual(f.port.status(receipt.command_id).phase,CommandPhase.UNKNOWN)
        self.assertEqual(len(f.transport.writes),1)

    def test_lease_expiration_in_guard_and_fresh_command_recovery(self):
        f=self.fx;receipt=self.submit(1,ArmEffect(),101,deadline=190)
        lease=f.authority.lease
        f.authority._lease=replace(lease,expires_at=at(105))
        f.port._write_guard=lambda command:setattr(f,'now_ns',106)
        f.now_ns=102;f.port.write_next(at(102))
        self.assertEqual(f.transport.writes,[])
        self.assertEqual(f.transport.attempts,[])
        self.assertEqual(f.port.status(receipt.command_id).phase,CommandPhase.REJECTED)
        f.authority._lease=lease;f.port._write_guard=None
        receipt=self.submit(2,ArmEffect(),107)
        f.now_ns=108;f.port.write_next(at(108))
        self.assertEqual(len(f.transport.writes),1)
        self.assertEqual(f.codec.feed(f.transport.writes[-1])[0].get_seq(),0)

    def test_guard_budget_invalid_return_and_authority_mutation_never_write(self):
        from vehicle_autonomy.vehicles.ardupilot.command_port import WriteGuardApproval
        cases=(lambda f: lambda command:setattr(f,'now_ns',60_000_110),
               lambda f: lambda command:False,
               lambda f: lambda command:WriteGuardApproval(at(101)),
               lambda f: lambda command:WriteGuardApproval('invalid-clock'),
               lambda f: lambda command:f.authority.set_system_send(False),
               lambda f: lambda command:f.authority.set_action_send(False),
               lambda f: lambda command:f.authority.set_link_session('other'),
               lambda f: lambda command:f.authority.grant(f.authority.lease,at(102)))
        for index,make in enumerate(cases):
            with self.subTest(index=index):
                self.setUp();f=self.fx
                receipt=self.submit(1,ArmEffect(),101,deadline=190)
                f.port._write_guard=make(f);f.now_ns=102
                f.port.write_next(at(102))
                self.assertEqual(f.transport.writes,[])
                self.assertEqual(f.transport.attempts,[])
                self.assertEqual(f.port.status(receipt.command_id).phase,CommandPhase.REJECTED)

    def test_actual_wire_order_cancellation_encoding_failure_and_transport_failure(self):
        from vehicle_autonomy.contracts.vehicle.command import CancelCommandRequest
        f=self.fx
        first=self.submit(1,ModeEffect('GUIDED'));f.now_ns=102;f.port.write_next(at(102))
        blocked=self.submit(2,ModeEffect('GUIDED'),103)
        cancelled=self.submit(3,ArmEffect(),104)
        f.port.cancel(CancelCommandRequest(cancelled.command_id,at(104)))
        arm=self.submit(4,ArmEffect(),105);f.now_ns=106;f.port.write_next(at(106))
        # Another command ID can bypass an ACK-blocked 176; sequence follows wire.
        parsed=f.codec.feed(b''.join(f.transport.writes))
        self.assertEqual([(m.command,m.get_seq()) for m in parsed],[(176,0),(400,1)])
        self.assertEqual(f.port.status(blocked.command_id).phase,CommandPhase.ACCEPTED)
        self.assertEqual(f.port.status(cancelled.command_id).phase,CommandPhase.CANCELLED)
        f.transport.incoming.append(pack(f.sender.command_ack_encode(176,0),f.sender));f.session.poll(at(107))
        f.transport.incoming.append(f.heartbeat());f.session.poll(at(108))
        f.now_ns=109;f.port.write_next(at(109))
        self.assertEqual(f.codec.feed(f.transport.writes[-1])[0].get_seq(),2)
        # Encoding failure is rejected without consuming a sequence or calling transport.
        self.setUp();f=self.fx;request=self.submit(1,ArmEffect())
        encode=f.codec.encode
        def bad_encode(*a,**kw):raise ValueError('encoding rejected')
        f.codec.encode=bad_encode;f.now_ns=102;f.port.write_next(at(102))
        self.assertEqual(f.transport.writes,[])
        self.assertEqual(f.transport.attempts,[])
        self.assertEqual(f.port.status(request.command_id).phase,CommandPhase.REJECTED)
        f.codec.encode=encode;self.submit(2,ArmEffect(),103)
        f.transport.fail_write=True;f.now_ns=104;f.port.write_next(at(104))
        self.assertEqual(f.transport.writes,[])
        self.assertEqual(len(f.transport.attempts),1)
        self.assertTrue(f.port._write_uncertain)
        self.assertEqual(f.codec._sender.seq,1)
        self.assertIsNone(f.port.write_next(at(105)))
        fresh=MavlinkCodec(source_system=250,source_component=191,target_system=1,target_component=1)
        self.assertEqual(fresh.feed(fresh.encode(CommandLong(400,(1.,0.,0.,0.,0.,0.,0.))))[0].get_seq(),0)

    def test_queued_writer_sequence_wrap_with_cancelled_and_rejected_motion(self):
        from itertools import count
        from vehicle_autonomy.contracts.core.geometry import Twist3, Vector3
        from vehicle_autonomy.contracts.effects.vehicle import TwistTargetEffect
        from vehicle_autonomy.contracts.vehicle.command import CancelCommandRequest
        f=self.fx;ids=count();f.execution._command_ids=lambda:f'wire-{next(ids)}'
        f.now_ns=102;receipts=[]
        for index in range(260):
            receipts.append(f.execution.dispatch(effect(index+1,TwistTargetEffect('base_link',
                Twist3(Vector3(.2,0,0),Vector3(0,0,0)),f'wire-stream-{index}')),world(),at(102)).receipt)
        self.assertEqual(f.transport.attempts,[])
        f.port.cancel(CancelCommandRequest(receipts[17].command_id,at(102)))
        f.port._write_guard=lambda command:'injected_rejection' if command.command_id==receipts[128].command_id else None
        for _ in range(261):f.port.write_next(at(1))  # stale caller time cannot control the fence
        frames=f.codec.feed(b''.join(f.transport.writes))
        self.assertEqual(len(f.transport.attempts),258)
        self.assertEqual([m.get_seq() for m in frames],list(range(256))+[0,1])
        self.assertTrue(all(m.get_type()=='SET_POSITION_TARGET_LOCAL_NED' for m in frames))
        self.assertEqual(f.port.status(receipts[17].command_id).phase,CommandPhase.CANCELLED)
        self.assertEqual(f.port.status(receipts[128].command_id).phase,CommandPhase.REJECTED)

    def test_transport_returning_after_deadline_is_unknown_and_never_retried(self):
        f=self.fx;receipt=self.submit(1,ArmEffect(),101,deadline=110)
        original=f.transport.write
        def late_write(data):
            original(data)
            f.now_ns=111
        f.transport.write=late_write;f.now_ns=102
        f.port.write_next(at(1))
        self.assertEqual(len(f.transport.attempts),1)
        self.assertEqual(f.port.status(receipt.command_id).phase,CommandPhase.UNKNOWN)
        self.assertIn('transport_returned_after_fence',f.port.reasons[receipt.command_id])
        self.assertIsNone(f.port.write_next(at(112)))
        self.assertEqual(len(f.transport.attempts),1)
