"""Real AP telemetry, rejection bytes, late ACK and repeated connection probe.

Motion acceptance remains in the existing physical scenarios. Only explicit
owned localhost fixtures are allowed; no protocol command is sent directly.
"""
from dataclasses import replace
from datetime import timedelta
import argparse
import json
import math
import os
from pathlib import Path
import time
from uuid import uuid4

from vehicle_autonomy.app.bootstrap.simulation_runtime import SimulationRuntime
from vehicle_autonomy.contracts.core.geometry import Twist3, Vector3
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.core.primitives import SchemaVersion
from vehicle_autonomy.contracts.effects.vehicle import EffectEnvelope, ModeEffect, TakeoffEffect, TwistTargetEffect
from vehicle_autonomy.contracts.vehicle.telemetry import TelemetryAvailability as A
from vehicle_autonomy.engine.control.control_authority import ControlLease
from vehicle_autonomy.vehicles.ardupilot.commands import ArduPilotCommandTranslator
from vehicle_autonomy.vehicles.ardupilot.transports.bytes import TcpByteTransport
from vehicle_autonomy.vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator
from tests.simulation.launch import OwnedSimulation, ROOT, available, install_signal_cleanup
from tests.simulation.faults import TcpFaultProxy
from tests.simulation.oracle import GazeboTruthOracle


def shifted(point, ns):
    return replace(point, monotonic_ns=point.monotonic_ns + ns,
                   utc=point.utc + timedelta(microseconds=ns // 1000))


def socket_ids():
    result = set()
    for path in Path('/proc/self/fd').iterdir():
        try:
            value = os.readlink(path)
        except FileNotFoundError:
            continue
        if value.startswith('socket:'):
            result.add(value)
    return result


def run(run_dir, kind, *, review_remediation=False):
    run_dir.mkdir(parents=True, exist_ok=False)
    owned = OwnedSimulation(run_dir, kind)
    runtime = proxy = None
    writes = []
    evidence = (run_dir / 'telemetry.jsonl').open('w')
    events = (run_dir / 'runtime.jsonl').open('w')
    summary = dict(passed=False, kind=kind, groups={}, run_dir=str(run_dir))
    closed_sockets = set()
    cycles = 0
    try:
        owned.start()
        oracle = GazeboTruthOracle(owned.world, owned.model)
        proxy = TcpFaultProxy(owned.port, run_dir / 'proxy.jsonl', capture_payload=True)
        profile = replace(owned.profile, port=proxy.port)

        class ObservedTransport:
            def __init__(self, transport):
                self.transport = transport
            def read(self, *args):
                return self.transport.read(*args)
            def write(self, data):
                writes.append({'host_ns': time.monotonic_ns(), 'bytes': len(data), 'raw_hex': data.hex()})
                self.transport.write(data)
            def close(self):
                self.transport.close()

        def connect(host, port, **kwargs):
            if host != '127.0.0.1' or port != proxy.port:
                raise AssertionError('only our owned loopback proxy may connect')
            return ObservedTransport(TcpByteTransport.connect(host, port, **kwargs))

        def new_runtime():
            translator = (ArduRoverCommandTranslator if kind == 'rover' else ArduPilotCommandTranslator)(mode_ids=profile.mode_ids)
            selected = SimulationRuntime(profile, translator=translator, transport_factory=connect,
                event_sink=lambda e: (events.write(json.dumps(e)+'\n'), events.flush()))
            selected.connect()
            return selected

        runtime = new_runtime()

        def cycle(allow_fault=False):
            nonlocal cycles
            started = time.monotonic()
            owned.assert_alive()
            if proxy.error:
                raise RuntimeError(proxy.error)
            result = runtime.cycle()
            cycles += 1
            if result.fault and not allow_fault:
                raise RuntimeError(result.fault)
            world = runtime.world_snapshot()
            state = None if world is None else world.vehicle
            truth = oracle.latest()
            evidence.write(json.dumps({'host_ns': time.monotonic_ns(), 'cycle': to_json_value(result),
                'link': to_json_value(runtime.link_snapshot()), 'telemetry': to_json_value(runtime.telemetry_snapshot()),
                'state': to_json_value(state), 'truth': to_json_value(truth)})+'\n')
            evidence.flush()
            time.sleep(max(0, profile.period_ns / 1e9 - (time.monotonic()-started)))
            return state, truth, result

        def pump(seconds):
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                cycle()

        def warm(seconds=45):
            pump(seconds)
            state, truth, _ = cycle()
            if (not state or not state.reported_pose or not state.reported_twist or not truth
                    or time.monotonic_ns()-truth.host_received_ns >= 500_000_000):
                raise AssertionError('fresh AP state and independent Gazebo truth required')
            return state, truth

        state, truth = warm()
        view = runtime.telemetry_snapshot()
        hb = view.field('HEARTBEAT')
        if (hb.value.mav_type != profile.mav_type or hb.value.autopilot != 3
                or (view.source_system, view.source_component) != (1, 1)
                or not runtime.link_snapshot().connected or writes):
            raise AssertionError('connection, identity or read-only receiving failed')
        summary['groups']['A'] = dict(passed=True, mav_type=hb.value.mav_type,
            session=runtime.session_id, heartbeat_observations=hb.observations,
            received_cycles=cycles, initial_command_writes=len(writes))
        for name in ('ATTITUDE', 'GLOBAL_POSITION_INT', 'GPS_RAW_INT'):
            if view.field(name).availability is not A.VALID:
                raise AssertionError(f'{name} not capture-qualified: {view.field(name)}')
        for name in ('EKF_STATUS_REPORT', 'SYS_STATUS', 'POWER_STATUS'):
            field = view.field(name)
            if field.value is None or not field.receive_fresh or field.captured_at is not None:
                raise AssertionError(f'{name} missing or fictional capture time')
        if kind == 'copter' and view.field('LOCAL_POSITION_NED').availability is not A.VALID:
            raise AssertionError('Copter local state missing')
        q = state.reported_pose.value.orientation
        yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
        yaw_error = abs(math.atan2(math.sin(yaw-truth.yaw_rad), math.cos(yaw-truth.yaw_rad)))
        v = state.reported_twist.value.linear
        truth_v = oracle.recent_velocity_enu()
        velocity_error = math.sqrt(sum((a-b)**2 for a,b in zip((v.x,v.y,v.z), truth_v)))
        if yaw_error > .1 or velocity_error > .15:
            raise AssertionError(f'ENU/FLU vs truth mismatch: yaw={yaw_error}, velocity={velocity_error}')
        summary['groups']['B'] = dict(passed=True, yaw_error_rad=yaw_error,
            velocity_error_mps=velocity_error, fields=to_json_value(view.fields),
            unavailable=[f.message_type for f in view.fields if f.value is None],
            motion_truth='separate full physical scenario compares ENU targets and measured displacement')

        # Every D case goes through the active Execution boundary; queue identity
        # mutation is explicitly a fault injected after Execution prepared it.
        rejections = {}
        def deny(name, operation, expected):
            before = len(writes)
            proxy_before = len(proxy.tx())
            started_ns = time.monotonic_ns()
            result = operation()
            for _ in range(3):
                cycle()
            reason = result.reason
            if reason != expected or len(writes) != before or len(proxy.tx()) != proxy_before:
                raise AssertionError(f'{name}: {reason}, writes={len(writes)-before}')
            rejections[name] = dict(passed=True, reason=reason, write_attempts=len(writes)-before, writer_bytes=0,
                                    proxy_tx_delta=len(proxy.tx())-proxy_before, started_ns=started_ns, ended_ns=time.monotonic_ns())

        runtime.begin_run()
        deny('default_send', lambda: runtime.submit_effect(ModeEffect('GUIDED'), effect_id='default'), 'system_send_disabled')
        runtime.end_run()
        runtime.begin_run(allow_send=True)
        runtime.authority.set_action_send(False)
        deny('action_send', lambda: runtime.submit_effect(ModeEffect('GUIDED'), effect_id='action-off'), 'action_send_disabled')
        runtime.authority.set_action_send(True)
        runtime.authority.revoke()
        runtime.authority.set_action_send(True)
        deny('missing_lease', lambda: runtime.submit_effect(ModeEffect('GUIDED'), effect_id='no-lease'), 'no_lease')
        runtime.authority.grant(ControlLease('wrong-scope', 'another-run', 'another-action', shifted(runtime.clock(), 10_000_000_000)), runtime.clock())
        runtime.authority.set_action_send(True)
        deny('invalid_lease', lambda: runtime.submit_effect(ModeEffect('GUIDED'), effect_id='bad-lease'), 'lease_scope_mismatch')
        runtime.end_run()
        runtime.begin_run(allow_send=True)
        def expired():
            now = runtime.clock()
            return runtime.dispatch_envelope(EffectEnvelope(SchemaVersion(1,0),'expired',runtime._run_id,runtime._action_id,
                shifted(now,-2_000_000_000),shifted(now,-1),ModeEffect('GUIDED')))
        deny('expired_command', expired, 'invalid_effect_time')
        deny('illegal_frame', lambda: runtime.submit_effect(TwistTargetEffect('bad-frame', Twist3(Vector3(0,0,0),Vector3(0,0,0)), 'bad'), effect_id='bad-frame'),
             'rover_drive_requires_planar_base_link' if kind=='rover' else 'frame_not_allowed')
        deny('unsupported_capability', lambda: runtime.submit_effect(TakeoffEffect(.1) if kind=='rover' else ModeEffect('PLANE_AUTO'), effect_id='unsupported'),
             'rover_flight_effect_unsupported' if kind=='rover' else 'mode_not_allowed')
        now = runtime.clock()
        stale_world = replace(runtime.world_snapshot(), published_at=shifted(now,-profile.safety.max_snapshot_age_ns-1))
        def stale():
            now = runtime.clock()
            envelope=EffectEnvelope(SchemaVersion(1,0),'stale-state',runtime._run_id,runtime._action_id,now,shifted(now,1_000_000_000),ModeEffect('GUIDED'))
            return runtime._execution.dispatch(envelope,stale_world,now)
        deny('expired_state', stale, 'world_stale')
        before = len(writes)
        admitted = runtime.submit_effect(ModeEffect('GUIDED'), effect_id='wrong-session')
        command_id = admitted.receipt.command_id
        runtime._port._commands[command_id] = replace(runtime._port._commands[command_id], expected_link_session_id='old-session')
        cycle()
        if runtime.effect_status('wrong-session')['reason'] != 'link_session_changed' or len(writes)!=before:
            raise AssertionError('wrong session wrote bytes')
        rejections['wrong_session'] = dict(passed=True, reason='link_session_changed', writer_bytes=0, write_attempts=0)
        summary['groups']['D'] = dict(passed=True, cases=rejections,
            evidence='actual transport.write attempts plus loopback proxy raw TX; stale world and queued identity explicitly injected')

        runtime.end_run()
        if review_remediation:
            from tests.simulation.remediation_cases import run as review_cases
            summary["remediation"] = review_cases(runtime, proxy, pump, writes)

        # Duplicated real AP packets retain their original capture AND receive age.
        proxy.inject(duplicate_rx={'ATTITUDE'})
        pump(1)
        proxy.inject(duplicate_rx=set(), repeat_pose=True)
        pump(4)
        view = runtime.telemetry_snapshot()
        att = view.field('ATTITUDE')
        if att.duplicates < 2 or att.availability is not A.STALE:
            raise AssertionError(f'repeated source became fresh: {att}')
        summary['repeat_telemetry'] = dict(passed=True, duplicates=att.duplicates,
            capture_ns=att.captured_at.monotonic_ns, received_ns=att.received_at.monotonic_ns,
            status=att.availability.value)
        proxy.inject(repeat_pose=False)
        pump(2)
        # ACK is generated by the real AP in response to Execution, delayed past
        # its original TTL, then delivered; the old result must stay UNKNOWN.
        runtime.begin_run(allow_send=True)
        proxy.inject(delay_ack_s=6.0)
        admitted = runtime.submit_effect(ModeEffect('GUIDED'), effect_id='late-ack')
        if admitted.reason:
            raise AssertionError(admitted.reason)
        pump(7.2)
        result = runtime.effect_status('late-ack')
        if result['phase']!='UNKNOWN' or result['reason']!='ack_timeout_outcome_unknown':
            raise AssertionError(f'late ACK falsely completed: {result}')
        before=len(writes)
        runtime.submit_effect(ModeEffect('GUIDED'),effect_id='ambiguous-queue')
        pump(5.5)
        queued=runtime.effect_status('ambiguous-queue')
        if queued['phase']!='REJECTED' or queued['reason']!='expired' or len(writes)!=before:
            raise AssertionError(f'ACK fenced queue replayed or never expired: {queued}')
        summary['late_ack'] = dict(passed=True, final=result, queued=queued,
                                   new_tx_under_ambiguity=0, delay_s=6.)
        proxy.inject(delay_ack_s=0.)
        runtime.end_run()

        # Heartbeat-only loss: other real telemetry continues flowing.
        old_session=runtime.session_id
        proxy.inject(drop_rx={'HEARTBEAT'})
        until=time.monotonic()+5
        while time.monotonic()<until:
            _,_,result=cycle(allow_fault=True)
            if result.fault:
                break
        else:
            raise AssertionError('heartbeat-only timeout not detected')
        if runtime.authority.lease is not None or runtime.authority.system_send or runtime.session_id:
            raise AssertionError('heartbeat loss retained authority/session')
        summary['heartbeat_timeout']=dict(passed=True, fault=result.fault, old_session=old_session)
        proxy.inject(drop_rx=set())
        runtime.connect()
        warm(3)
        reconnect_write_count=len(writes)
        sessions=[old_session, runtime.session_id]
        reconnects=[]
        for index in range(3):
            before_ids=socket_ids()
            runtime.shutdown()
            closed=before_ids-socket_ids()
            closed_sockets.update(closed)
            runtime=new_runtime()
            state,_=warm(3)
            sessions.append(runtime.session_id)
            view=runtime.telemetry_snapshot()
            if (runtime.authority.system_send or runtime.authority.action_send or runtime.authority.lease
                    or view.link_session_id != runtime.session_id
                    or view.field('COMMAND_ACK').value is not None):
                raise AssertionError('reconnection retained old authority or ACK state')
            reconnects.append(dict(session=runtime.session_id, closed_socket_ids=sorted(closed),
                                   receive_cycles=cycles, fd_count=len(list(Path('/proc/self/fd').iterdir()))))
        if len(set(sessions))!=len(sessions) or closed_sockets & socket_ids() or len(writes)!=reconnect_write_count:
            raise AssertionError('session reused or closed runtime socket leaked')
        summary['groups']['F']=dict(passed=True, sessions=sessions,reconnects=reconnects,
            cycles=cycles, closed_runtime_sockets=sorted(closed_sockets), replay_writes=len(writes)-reconnect_write_count)
        summary['groups']['E']=dict(passed=True, repeated_telemetry=summary['repeat_telemetry'],
            delayed_ack=summary['late_ack'], heartbeat_timeout=summary['heartbeat_timeout'],
            remaining_faults='dedicated existing physical fault scenario: link cut, SITL reboot, uncertain stop, no replay')
        summary['passed']=True
    except Exception as exc:
        summary['error']=f'{type(exc).__name__}: {exc}'
    finally:
        for name, close in [('runtime',lambda: runtime.shutdown() if runtime else None),
                            ('proxy',lambda: proxy.close() if proxy else None),('owned',owned.close)]:
            try:
                close()
            except Exception as exc:
                summary[name+'_cleanup_error']=f'{type(exc).__name__}: {exc}'
        summary['writer_attempts']=writes
        summary['proxy_port_released']=proxy is None or available(proxy.port)
        if any(key.endswith('_error') for key in summary) or not summary['proxy_port_released']:
            summary['passed']=False
        evidence.close()
        events.close()
        (run_dir/'summary.json').write_text(json.dumps(summary,indent=2))
    return summary


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--kind',choices=('copter','rover'),required=True)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--allow-send',action='store_true')
    parser.add_argument('--review-remediation',action='store_true')
    args=parser.parse_args()
    if not args.allow_send:
        parser.error('explicit --allow-send required for the owned localhost fixture')
    install_signal_cleanup()
    result=run(args.run_dir.resolve(),args.kind,review_remediation=args.review_remediation)
    print(json.dumps(result))
    return 0 if result['passed'] else 1

if __name__=='__main__':
    raise SystemExit(main())
