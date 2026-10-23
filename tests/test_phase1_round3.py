"""Round-3: indistinguishable unsigned input must degrade, not gain freshness."""
import hashlib
import unittest
from pymavlink.dialects.v20 import ardupilotmega as mav
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect, DisarmEffect
from vehicle_autonomy.vehicles.ardupilot.mavlink.signing import ReceiveSigning
from vehicle_autonomy.vehicles.ardupilot.mavlink.codec import MavlinkCodec
from tests.mavlink_fixture import pack, heartbeat_evidence, TEST_KEY
from tests import test_simulation_runtime as simtest
from tests import test_phase1_remediation as reviewtest
from tests import test_sitl_arm_mission as armsuite
from tests.test_p5_mavlink import at


class Round3ConfirmationTests(unittest.TestCase):
    def test_typed_disarm_action_does_not_succeed_from_wrap_replay(self):
        f=armsuite.SitlArmMissionTests();f.setUp();r=f.make_runtime()
        old_state=f.heartbeat(mode=4,armed=False)
        f.transport.incoming.append(old_state);f.cycle(r,heartbeat=False)
        f.transport.incoming.append(f.ack());f.cycle(r,heartbeat=False)
        f.advance_until_writes(r,2)
        old_ack=pack(f.sender.command_ack_encode(400,0),f.sender)
        f.transport.incoming.append(old_ack);f.cycle(r,heartbeat=False)
        f.advance_until_writes(r,3,armed=True)
        self.assertEqual(r.get_status()['step_id'],'disarm')
        for _ in range(3):
            boot=f.clock.ns//1_000_000+3  # prior heartbeat fixture ended at boot+2
            raw=b''.join(pack(f.sender.attitude_encode(boot+i,0,0,0,0,0,0),f.sender) for i in range(90))
            f.transport.incoming.append(raw);f.cycle(r,heartbeat=False)
        f.transport.incoming.append(old_ack+old_state);status=f.cycle(r,heartbeat=False)
        self.assertEqual(status['status'],'RUNNING')
        self.assertEqual(status['step_id'],'disarm')
        self.assertTrue(status['armed'])
        self.assertEqual(list(status['effects'].values())[-1]['phase'],'TRANSMITTED')
        self.assertEqual(len(f.transport.writes),3)
        f.transport.incoming.append(pack(f.sender.command_ack_encode(400,0),f.sender));f.cycle(r,heartbeat=False)
        for _ in range(5):
            status=f.cycle(r,armed=False)
            if status['status']=='SUCCEEDED':break
        self.assertEqual(status['status'],'SUCCEEDED')
        self.assertFalse(status['armed'])
        self.assertEqual(len(f.transport.writes),3)
        r.shutdown()

    def replay_case(self, wraps, unsigned=False):
        f=simtest.SimulationRuntimeTests();f.setUp();r=f.runtime;r.connect();s=f.sender;boot=1000
        def step(raw):
            f.clock.ns+=10_000_000 if wraps==1 else 1_000_000
            f.transports[-1].incoming.append(raw)
            result=r.cycle()
            self.assertIsNone(result.fault)
        def evidence(armed):
            nonlocal boot
            boot+=10
            raw=heartbeat_evidence(s,2,4,armed,boot);boot+=3
            return raw
        init=evidence(False)
        old_hbs=[bytes(m.get_msgbuf()) for m in mav.MAVLink(None).parse_buffer(init) if m.get_type()=='HEARTBEAT']
        step(init);r.begin_run(allow_send=True)
        def source(target):
            nonlocal boot
            for _ in range(256):
                boot+=10 if wraps==1 else 1
                raw=pack(s.attitude_encode(boot,0,0,0,0,0,0),s);step(raw)
                if raw[4]==target:return
            self.fail('8-bit target sequence not reached')
        source(253)
        r.submit_effect(ArmEffect(),effect_id='arm');step(b'')
        ack=pack(s.command_ack_encode(400,0,target_system=250,target_component=191),s)
        step(ack);step(evidence(True))
        self.assertEqual(r.effect_status('arm')['phase'],'COMPLETED')
        r.submit_effect(DisarmEffect(),effect_id='disarm');step(b'')
        for _ in range(wraps):
            source(253)
            if unsigned:
                # Same ambiguous command/state content with no authentication,
                # including new headers: no finite byte cache can solve this.
                u=mav.MAVLink(None,srcSystem=1,srcComponent=1);u.seq=254
                replay_ack=u.command_ack_encode(400,0).pack(u)
                replay_hbs=[]
                for seq in (1,3):
                    u.seq=seq;replay_hbs.append(u.heartbeat_encode(2,3,0,4,4).pack(u))
            else:replay_ack,replay_hbs=ack,old_hbs
            step(replay_ack)
            boot+=1;pack(s.attitude_encode(boot,0,0,0,0,0,0),s) # dropped source frame
            source(0)
            for raw in replay_hbs:
                step(raw)
                boot+=1;pack(s.attitude_encode(boot,0,0,0,0,0,0),s)
                source((raw[4]+1)&255)
            self.assertNotEqual(r.effect_status('disarm')['phase'],'COMPLETED')
            self.assertTrue(r._session.snapshot().operation.armed)
            self.assertTrue(r.world_snapshot().vehicle.operation.armed)
            self.assertEqual(len(f.transports[-1].writes),2)
            self.assertNotIn(r._effects['disarm'],r._port.ack_evidence)
            step(evidence(True))
        # Fresh independently verified ACK + state, same live request, works.
        step(pack(s.command_ack_encode(400,0),s));step(evidence(False))
        self.assertEqual(r.effect_status('disarm')['phase'],'COMPLETED')
        self.assertFalse(r.world_snapshot().vehicle.operation.armed)
        frames=mav.MAVLink(None).parse_buffer(b''.join(f.transports[-1].writes))
        self.assertEqual([(m.command,m.param1) for m in frames],[(400,1),(400,0)])
        self.assertGreater(sum(r._receive_signing.rejected.values()),0)
        r.shutdown()

    def test_exact_second_review_wrap_replay_then_real_disarm(self):
        self.replay_case(1)

    def test_three_wraps_signed_old_ack_and_heartbeats(self):
        self.replay_case(3)

    def test_three_wraps_unsigned_indistinguishable_state_degrades(self):
        self.replay_case(3,unsigned=True)

    def test_unsigned_confirmation_unknown_and_signed_recovery_other_request(self):
        f=reviewtest.ReviewReproductions();f.setUp();x=f.fx
        receipt=f.submit(1,ArmEffect());x.now_ns=102;x.port.write_next(at(102))
        # Receiving fresh timed telemetry cannot bless this unsigned ACK/HB.
        u=mav.MAVLink(None,srcSystem=1,srcComponent=1)
        raw=u.command_ack_encode(400,0).pack(u)+u.heartbeat_encode(2,3,128,4,4).pack(u)
        x.transport.incoming.append(raw+x.heartbeat());x.session.poll(at(103))
        self.assertEqual(x.port.status(receipt.command_id).phase.value,'TRANSMITTED')
        self.assertNotIn(receipt.command_id,x.port.ack_evidence)
        self.assertFalse(x.session.snapshot().operation.armed)
        x.now_ns=180;x.port.expire_unknown(at(180))
        self.assertEqual(x.port.status(receipt.command_id).phase.value,'UNKNOWN')
        self.assertEqual(len(x.transport.attempts),1)

    def test_invalid_mac_cannot_poison_watermark_and_wrong_stream_is_bounded(self):
        verifier=ReceiveSigning(TEST_KEY,initial_timestamp=0)
        codec=MavlinkCodec(source_system=250,source_component=191,target_system=1,target_component=1,receive_signing=verifier)
        sender=mav.MAVLink(None,srcSystem=1,srcComponent=1)
        first=pack(sender.heartbeat_encode(2,3,128,4,4),sender)
        self.assertIsNotNone(codec.feed(first)[0]._vaf_signature_timestamp)
        old=verifier.watermark
        invalid=bytearray(first);invalid[-12:-6]=(2**48-1).to_bytes(6,'little')
        self.assertIsNone(codec.feed(bytes(invalid))[0]._vaf_signature_timestamp)
        self.assertEqual(verifier.watermark,old)
        sender.signing.link_id=1
        wrong=pack(sender.heartbeat_encode(2,3,0,4,4),sender)
        self.assertIsNone(codec.feed(wrong)[0]._vaf_signature_timestamp)
        sender.signing.link_id=0
        fresh=pack(sender.heartbeat_encode(2,3,128,4,4),sender)
        self.assertIsNotNone(codec.feed(fresh)[0]._vaf_signature_timestamp)
        self.assertIsNone(codec.feed(first)[0]._vaf_signature_timestamp)
        self.assertEqual(set(verifier.rejected),{'unsigned','signature','stream','replay'})

    def test_reconnect_retains_watermark_new_epoch_rejects_old_mac(self):
        f=simtest.SimulationRuntimeTests();f.setUp();r=f.runtime;r.connect()
        old=f.heartbeat(mode=4,armed=True);f.cycle(old+f.state_messages())
        watermark=r._receive_signing.watermark;session=r.session_id
        f.transports[-1].disconnected=True;f.cycle()
        r.connect();f.cycle(old)
        self.assertEqual(r._receive_signing.watermark,watermark)
        self.assertIsNone(r._session.snapshot())
        self.assertIsNone(r.world_snapshot().vehicle)
        f.cycle(f.heartbeat(mode=4,armed=True)+f.state_messages())
        self.assertNotEqual(session,r.session_id)
        self.assertTrue(r.world_snapshot().vehicle.operation.armed)
        self.assertEqual(sum(len(t.writes) for t in f.transports),0)
        new=ReceiveSigning(hashlib.sha256(TEST_KEY).digest(),initial_timestamp=0)
        message=mav.MAVLink(None).parse_buffer(old)[1]
        self.assertIsNone(new.verify(message,system=1,component=1))
        r.shutdown()

    def test_long_stream_many_wraps_fixed_memory_and_live_armed_state(self):
        f=simtest.SimulationRuntimeTests();f.setUp();r=f.runtime;r.connect()
        verifier_fields=set(vars(r._receive_signing))
        for index in range(10000):
            # 70000 authenticated frames, >270 sequence wraps / 1000 simulated
            # seconds; keep supplying
            # real operation changes to prove availability, not only rejection.
            f.cycle(f.heartbeat(mode=4,armed=bool(index%2))+f.state_messages())
            self.assertEqual(r.world_snapshot().vehicle.operation.armed,bool(index%2))
            self.assertLessEqual(len(r._session._pending_packets),256)
        self.assertGreaterEqual(r._receive_signing.accepted,70000)
        self.assertEqual(set(vars(r._receive_signing)),verifier_fields)
        self.assertEqual(r._receive_signing.rejected,dict(unsigned=0,signature=0,replay=0,stream=0))
        self.assertEqual(f.transports[-1].writes,[])
        self.assertEqual(len(r._port._statuses),0)
        r.shutdown()


if __name__=='__main__':unittest.main()
