"""Real TAKEOFF write before motion telemetry: cancellation stays unknown."""
import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import time
from vehicle_autonomy.app.bootstrap.simulation_runtime import SimulationRuntime
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect, ModeEffect
from vehicle_autonomy.vehicles.ardupilot.transports.bytes import TcpByteTransport
from vehicle_autonomy.vehicles.plane.ardupilot_commands import ArduPlaneCommandTranslator
from tests.simulation.faults import TcpFaultProxy
from tests.simulation.launch import OwnedSimulation, install_signal_cleanup
from tests.simulation.oracle import GazeboTruthOracle


def run(path):
    path.mkdir(parents=True, exist_ok=False)
    owned=OwnedSimulation(path,'plane',confirmation_signing=True)
    runtime=proxy=None;writes=[];report=dict(passed=False)
    events=(path/'runtime.jsonl').open('w');trace=(path/'trajectory.jsonl').open('w')
    try:
        owned.start();oracle=GazeboTruthOracle(owned.world,owned.model)
        proxy=TcpFaultProxy(owned.port,path/'proxy.jsonl',capture_payload=True)
        profile=replace(owned.profile,port=proxy.port)
        class ObservedTransport:
            def __init__(self,transport):self.transport=transport
            def read(self,*a,**kw):return self.transport.read(*a,**kw)
            def write(self,data):
                writes.append(dict(host_ns=time.monotonic_ns(),raw_hex=data.hex()))
                self.transport.write(data)
            def close(self):self.transport.close()
        def connect(host,port,**kwargs):
            if (host,port)!=('127.0.0.1',proxy.port):raise RuntimeError('owned proxy required')
            return ObservedTransport(TcpByteTransport.connect(host,port,**kwargs))
        runtime=SimulationRuntime(profile,receive_signing=owned.receive_signing,
            translator=ArduPlaneCommandTranslator(mode_ids=profile.mode_ids),transport_factory=connect,
            event_sink=lambda e:(events.write(json.dumps(e)+'\n'),events.flush()))
        runtime.connect()
        def cycle():
            owned.assert_alive();result=runtime.cycle()
            if result.fault:raise RuntimeError(result.fault)
            time.sleep(profile.period_ns/1e9)
        until=time.monotonic()+45
        while time.monotonic()<until:cycle()
        runtime.begin_run(allow_send=True)
        admitted=runtime.submit_effect(ArmEffect(),effect_id='arm')
        if admitted.reason:raise AssertionError(admitted.reason)
        until=time.monotonic()+7
        while time.monotonic()<until:
            cycle()
            if runtime.effect_status('arm')['phase']=='COMPLETED':break
        else:raise TimeoutError('normal Arm before cancellation window')
        state=runtime.world_snapshot().vehicle;origin=oracle.latest()
        if state is None or origin is None or not state.operation.armed:raise AssertionError('armed ground required')
        before=len(writes)
        proxy.inject(drop_ack_commands={176})
        admitted=runtime.submit_effect(ModeEffect('TAKEOFF'),effect_id='takeoff-window')
        if admitted.reason:raise AssertionError(admitted.reason)
        # One cycle reads state BEFORE its write. Do not wait for a new
        # heartbeat or moving sample before cancelling the transmitted mode.
        result=runtime.cycle()
        state=runtime.world_snapshot().vehicle
        if result.fault or len(writes)!=before+1 or runtime.effect_status('takeoff-window')['phase']!='TRANSMITTED':
            raise AssertionError('exactly one actual TAKEOFF writer call required')
        if abs(state.reported_pose.value.position.z)>1.5 or max(abs(v) for v in (
                state.reported_twist.value.linear.x,state.reported_twist.value.linear.y,state.reported_twist.value.linear.z))>1:
            raise AssertionError('did not exercise stationary-ground telemetry window')
        # Let the real AP process its mode command, while the application still
        # has exactly the pre-write ground state. Observing TX alone would not
        # prove that the peer processed bytes before the socket was closed.
        until=time.monotonic()+1;accepted=False
        while time.monotonic()<until:
            with proxy._lock:
                accepted=any(r.get('direction')=='rx' and r.get('type')=='COMMAND_ACK'
                    and r['payload']['command']==176 and r['payload']['result']==0 for r in proxy.records)
            if accepted:break
            time.sleep(.01)
        if not accepted:raise AssertionError('real peer TAKEOFF ACK not observed at proxy')
        from tests.simulation.native_boundaries import assert_handoff_blocked
        report['action_handoff']=assert_handoff_blocked(runtime)
        stops=runtime.end_run()
        if stops!={'fixed-wing-flight':'UNCONFIRMED'} or len(writes)!=before+1:
            raise AssertionError('latched TAKEOFF lost uncertainty or sent unsafe recovery')
        if runtime.authority.system_send or runtime.authority.lease or runtime.session_id is not None:
            raise AssertionError('cancel retained authorization/session')
        after=runtime.world_snapshot().vehicle
        if after!=state or not after.operation.armed:
            raise AssertionError('last known World sample was rewritten as cancellation proof')
        status=runtime.effect_status('takeoff-window')
        if status['phase']!='UNKNOWN':raise AssertionError('abandoned command outcome must stay unknown')
        # Independent observation shows why the old ground sample cannot prove
        # a stop: the already forwarded native command can start moving later.
        until=time.monotonic()+5;distance=0.;speed=0.
        while time.monotonic()<until:
            owned.assert_alive();truth=oracle.latest()
            if truth is None or time.monotonic_ns()-truth.host_received_ns>500_000_000:
                raise AssertionError('fresh independent truth required')
            distance=math.hypot(truth.x_m-origin.x_m,truth.y_m-origin.y_m)
            speed=oracle.recent_speed_mps() or 0.
            trace.write(json.dumps(dict(host_ns=time.monotonic_ns(),truth=[truth.x_m,truth.y_m,truth.z_m],speed=speed))+'\n')
            if distance>=.5 and speed>.5:break
            time.sleep(.1)
        else:raise AssertionError('native TAKEOFF was not actually forwarded/latched')
        # Reconnect solely to observe; no new grant or old request may survive.
        previous_session=str(after.telemetry.link_session_id)
        runtime.connect();until=time.monotonic()+1.5
        while time.monotonic()<until:cycle()
        fresh=runtime.world_snapshot().vehicle
        if (runtime.session_id==previous_session or runtime.authority.system_send
                or runtime.authority.action_send or runtime.authority.lease or fresh is None
                or str(fresh.telemetry.link_session_id)!=runtime.session_id or not fresh.operation.armed):
            raise AssertionError('read-only reconnect carried authorization or lacks fresh state')
        if runtime.shutdown()!={'fixed-wing-flight':'UNCONFIRMED'} or len(writes)!=before+1:
            raise AssertionError('read-only reconnect lost flight uncertainty or wrote a command')
        report['read_only_reconnect']=dict(passed=True,stops={'fixed-wing-flight':'UNCONFIRMED'},writer_calls=0,
            new_session=str(fresh.telemetry.link_session_id),armed=fresh.operation.armed)
        report.update(passed=True,stops=stops,status=status,takeoff_writer_calls=1,recovery_writer_calls=0,peer_ack_observed_not_delivered=True,
            post_cancel_displacement_m=distance,post_cancel_ground_speed_mps=speed,
            world_after_cancel=dict(armed=after.operation.armed,native_mode=after.operation.native_mode,
                source_session=str(after.telemetry.link_session_id),current_session=runtime.session_id,
                capture_ns=after.reported_pose.captured_at.monotonic_ns,last_known_sample_unchanged=True))
    except BaseException as exc:report['error']=f'{type(exc).__name__}: {exc}'
    finally:
        for name,close in [('runtime',lambda:runtime.shutdown() if runtime else None),('proxy',lambda:proxy.close() if proxy else None),('owned',owned.close)]:
            try:close()
            except BaseException as exc:report[name+'_cleanup_error']=type(exc).__name__
        if any(k.endswith('_cleanup_error') for k in report):report['passed']=False
        report['writer_attempts']=writes;events.close();trace.close()
        (path/'summary.json').write_text(json.dumps(report,indent=2))
    return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--allow-send',action='store_true');p.add_argument('--run-dir',type=Path,required=True)
    a=p.parse_args()
    if not a.allow_send:p.error('--allow-send required for newly owned loopback fixtures')
    install_signal_cleanup();r=run(a.run_dir.resolve());print(json.dumps(r),flush=True)
    return 0 if r['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
