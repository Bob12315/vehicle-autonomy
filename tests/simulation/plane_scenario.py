"""Owned conventional Plane: real wheel rollout, flight and native AUTOLAND."""
from pymavlink.dialects.v20 import ardupilotmega as mav
from dataclasses import replace
import argparse
import json
import math
from pathlib import Path
import time
from vehicle_autonomy.app.bootstrap.simulation_runtime import SimulationRuntime
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect, DisarmEffect, ModeEffect, FixedWingTargetEffect
from vehicle_autonomy.contracts.core.geometry import GeoPoint
from vehicle_autonomy.vehicles.ardupilot.transports.bytes import TcpByteTransport
from tests.simulation.faults import TcpFaultProxy
from vehicle_autonomy.vehicles.plane.ardupilot_commands import ArduPlaneCommandTranslator
from tests.simulation.launch import OwnedSimulation, install_signal_cleanup
from tests.simulation.oracle import GazeboTruthOracle


def run(path):
    path.mkdir(parents=True, exist_ok=False)
    owned = OwnedSimulation(path, 'plane', confirmation_signing=True)
    runtime = proxy = None
    writes=[]
    report = dict(passed=False, steps={}, texts=[])
    events=(path/'runtime.jsonl').open('w'); trace=(path/'trajectory.jsonl').open('w')
    samples=[]
    try:
        owned.start()
        oracle=GazeboTruthOracle(owned.world, owned.model)
        proxy=TcpFaultProxy(owned.port,path/'proxy.jsonl',capture_payload=True)
        profile=replace(owned.profile,port=proxy.port)
        class ObservedTransport:
            def __init__(self,transport):
                self.transport=transport;self.parser=mav.MAVLink(None);self.parser.robust_parsing=True
            def read(self,*a,**kw):
                data=self.transport.read(*a,**kw)
                if data:
                    for m in self.parser.parse_buffer(data) or []:
                        if m.get_type()=='STATUSTEXT':report['texts'].append(str(m.text))
                        if m.get_type() in ('NAV_CONTROLLER_OUTPUT','VFR_HUD','ATTITUDE','GLOBAL_POSITION_INT'):
                            report.setdefault('latest_diagnostics',{})[m.get_type()]=m.to_dict()
                return data
            def write(self,data):
                writes.append(dict(host_ns=time.monotonic_ns(),raw_hex=data.hex()))
                self.transport.write(data)
            def close(self):self.transport.close()
        def connect(host,port,**kwargs):
            if host!='127.0.0.1' or port!=proxy.port:raise RuntimeError('only owned proxy allowed')
            return ObservedTransport(TcpByteTransport.connect(host,port,**kwargs))
        runtime=SimulationRuntime(profile, translator=ArduPlaneCommandTranslator(mode_ids=profile.mode_ids),
            receive_signing=owned.receive_signing,transport_factory=connect,event_sink=lambda e: (events.write(json.dumps(e)+'\n'),events.flush()))
        runtime.connect()
        def cycle(allow_fault=False):
            start=time.monotonic();owned.assert_alive()
            result=runtime.cycle()
            if result.fault and not allow_fault:raise RuntimeError(result.fault)
            state=runtime.world_snapshot().vehicle;truth=oracle.latest()
            if truth:
                if time.monotonic_ns()-truth.host_received_ns>500_000_000:raise RuntimeError('Gazebo truth stale')
                if truth.z_m>profile.safety.max_altitude_m or abs(truth.x_m)>2000 or abs(truth.y_m)>2000:
                    raise RuntimeError('independent truth exceeded declared Plane envelope')
                s=dict(host_ns=time.monotonic_ns(),sim_ns=truth.simulation_ns,
                    truth=[truth.x_m,truth.y_m,truth.z_m,truth.yaw_rad],speed=oracle.recent_speed_mps(),
                    vertical_speed=oracle.recent_vertical_speed_mps(),
                    armed=None if state is None else state.operation.armed,
                    mode=None if state is None else state.operation.native_mode,
                    fault=result.fault,diagnostics=report.get('latest_diagnostics',{}),
                    reported_position=None if state is None or state.reported_pose is None else
                      [state.reported_pose.value.position.x,state.reported_pose.value.position.y,state.reported_pose.value.position.z])
                trace.write(json.dumps(s)+'\n');trace.flush();samples.append(s)
            time.sleep(max(0,profile.period_ns/1e9-(time.monotonic()-start)))
            return state,truth
        end=time.monotonic()+45
        while time.monotonic()<end:state,truth=cycle()
        if not state or not state.reported_pose or not state.reported_twist or not truth:
            raise RuntimeError('fresh signed Plane state and independent truth required')
        baseline=truth.z_m; origin=(truth.x_m,truth.y_m)
        report['initial']=dict(altitude=baseline,position=origin,armed=state.operation.armed)
        global_ground_alt=state.global_position.value.altitude_m
        runtime.begin_run(allow_send=True)
        def command(name,effect):
            admitted=runtime.submit_effect(effect,effect_id=name)
            if admitted.reason:raise RuntimeError(f'{name}: {admitted.reason}')
            end=time.monotonic()+7
            while time.monotonic()<end:
                state,truth=cycle();status=runtime.effect_status(name)
                if status['phase']=='COMPLETED':
                    report['steps'][name]=status;return status
                if status['phase'] in ('REJECTED','UNKNOWN'):raise RuntimeError(f'{name}: {status}')
            raise TimeoutError(name)
        from tests.simulation.plane_regressions import ground
        report['regressions']=ground(runtime,proxy,cycle,command,writes)
        command('arm',ArmEffect())
        first=len(samples)
        command('takeoff-mode',ModeEffect('TAKEOFF'))
        end=time.monotonic()+120
        while time.monotonic()<end:
            state,truth=cycle()
            if truth.z_m-baseline>=45:break
        else:raise TimeoutError('physical climb to takeoff altitude')
        flight=samples[first:]
        rollout=[s for s in flight if s['truth'][2]-baseline<1.0 and (s['speed'] or 0)>8]
        if not rollout or max(math.hypot(s['truth'][0]-origin[0],s['truth'][1]-origin[1]) for s in rollout)<10:
            raise AssertionError('wheel rollout evidence missing; cannot count hand/vertical launch')
        report['takeoff']=dict(passed=True,height=truth.z_m-baseline,
            ground_rollout_samples=len(rollout),max_ground_rollout_speed=max(s['speed'] for s in rollout))
        state=runtime.world_snapshot().vehicle
        p=state.global_position.value
        target=GeoPoint(p.latitude_deg+math.degrees(150/6378137.),p.longitude_deg,global_ground_alt+50)
        command('native-target',FixedWingTargetEffect(target))
        # Native target COMPLETED is configuration evidence. Arrival/turning
        # requires later independent physical samples under fixed thresholds.
        destination=(truth.x_m,truth.y_m+150)
        end=time.monotonic()+90;stable=None;start_yaw=truth.yaw_rad;last_yaw=start_yaw;rotation=0.
        while time.monotonic()<end:
            state,truth=cycle()
            rotation+=abs(math.atan2(math.sin(truth.yaw_rad-last_yaw),math.cos(truth.yaw_rad-last_yaw)));last_yaw=truth.yaw_rad
            error=math.hypot(truth.x_m-destination[0],truth.y_m-destination[1])
            speed=oracle.recent_speed_mps()
            good=error<=120 and abs(truth.z_m-baseline-50)<=7 and speed is not None and 8<=speed<=28
            stable=(stable or time.monotonic()) if good else None
            if stable and time.monotonic()-stable>=3 and rotation>=math.pi/2:break
        else:raise TimeoutError('native fly-to/turn physical evidence missing')
        report['native_target']=dict(passed=True,target_amsl=[target.latitude_deg,target.longitude_deg,target.altitude_m],
            physical_center_error_m=error,absolute_turn_rad=rotation,ground_speed_mps=speed)
        command('loiter',ModeEffect('LOITER'))
        until=time.monotonic()+10
        while time.monotonic()<until:cycle()
        before=len(writes);previous_session=runtime.session_id
        stops=runtime.end_run()
        if stops!={'fixed-wing-flight':'UNCONFIRMED'}:raise AssertionError('fixed wing falsely reported stopped')
        recovery_frames=[proxy.frame_metadata(bytes.fromhex(w['raw_hex'])) for w in writes[before:]]
        if len(recovery_frames)!=1 or recovery_frames[0].get('type')!='COMMAND_LONG':
            raise AssertionError('cancel requires exactly one native recovery write')
        runtime.connect();until=time.monotonic()+1.5
        while time.monotonic()<until:cycle()
        if runtime.session_id==previous_session or runtime.authority.system_send or runtime.authority.lease:
            raise AssertionError('cancel/reconnect authorization carried over')
        if oracle.recent_speed_mps()<8:raise AssertionError('cancel did not retain flight')
        report['cancel']=dict(passed=True,physical_stop='UNCONFIRMED',recovery_frames=recovery_frames)
        runtime.begin_run(allow_send=True)
        command('rtl',ModeEffect('RTL'))
        until=time.monotonic()+8
        while time.monotonic()<until:cycle()
        previous_session=runtime.session_id;before=len(writes);proxy.disconnect()
        end=time.monotonic()+3
        while time.monotonic()<end:
            cycle(allow_fault=True)
            if runtime.session_id is None:break
        if runtime.session_id is not None or runtime.authority.system_send or runtime.authority.lease or len(writes)!=before:
            raise AssertionError('link loss retained authority or replayed writes')
        report['link_loss']=dict(passed=True,physical_stop='UNCONFIRMED',writer_calls=0)
        runtime.connect();until=time.monotonic()+1.5
        while time.monotonic()<until:cycle()
        if runtime.session_id==previous_session or runtime.authority.system_send or runtime.authority.lease:
            raise AssertionError('link reconnect retained authority')
        runtime.begin_run(allow_send=True)
        command('autoland-mode',ModeEffect('AUTOLAND'))
        end=time.monotonic()+360;stable=None
        while time.monotonic()<end:
            state,truth=cycle();speed=oracle.recent_speed_mps()
            ground=truth.z_m-baseline<.25 and speed is not None and speed<1
            stable=(stable or time.monotonic()) if ground else None
            if stable is not None and time.monotonic()-stable>=3:break
        else:raise TimeoutError('AUTOLAND physical touchdown and rollout stop')
        error=math.hypot(truth.x_m-origin[0],truth.y_m-origin[1])
        if error>80:raise AssertionError(f'landing outside declared runway target tolerance: {error}')
        if abs(truth.y_m-origin[1])>15:raise AssertionError('touchdown outside marked runway width')
        command('disarm',DisarmEffect())
        state=runtime.world_snapshot().vehicle
        if state.operation.armed:raise AssertionError('final disarmed state missing')
        report['landing']=dict(passed=True,home_error_m=error,height=truth.z_m-baseline,
            ground_speed_mps=speed,final_armed=state.operation.armed)
        report['passed']=True
    except BaseException as exc:
        report['error']=f'{type(exc).__name__}: {exc}'
    finally:
        for name,close in [('runtime',lambda:runtime.shutdown() if runtime else None),('proxy',lambda:proxy.close() if proxy else None),('owned',owned.close)]:
            try:close()
            except BaseException as exc:report[name+'_cleanup_error']=type(exc).__name__
        if any(k.endswith('_cleanup_error') for k in report):report['passed']=False
        report['writer_attempts']=writes
        events.close();trace.close()
        (path/'summary.json').write_text(json.dumps(report,indent=2))
    return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--allow-send',action='store_true');p.add_argument('--run-dir',type=Path,required=True)
    args=p.parse_args()
    if not args.allow_send:p.error('--allow-send required for newly owned loopback fixtures')
    install_signal_cleanup();result=run(args.run_dir.resolve());print(json.dumps(result),flush=True)
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
