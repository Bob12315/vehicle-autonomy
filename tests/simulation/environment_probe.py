"""Resolve named resources before Effect dispatch; truth is a separate judge."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import time
from uuid import uuid4
from contracts.core.geometry import Pose3, Quaternion, Twist3, Vector3
from contracts.effects.vehicle import ArmEffect, DisarmEffect, LandEffect, ModeEffect, PoseTargetEffect, StopMotionEffect, TakeoffEffect, TwistTargetEffect
from deployment.simulation_runtime import SimulationRuntime
from environments.resources import Environment
from tests.simulation.launch import ROOT, OwnedSimulation, install_signal_cleanup
from tests.simulation.oracle import GazeboTruthOracle
from vehicles.multirotor.ardupilot_commands import ArduPilotCommandTranslator
from vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator


def run(directory, kind):
    directory.mkdir(parents=True, exist_ok=False)
    owned = OwnedSimulation(directory, kind)
    runtime = None
    report = {"passed": False, "targets": {}}
    log = (directory/'runtime.jsonl').open('w')
    samples = (directory/'observations.jsonl').open('w')
    try:
        owned.start()
        oracle = GazeboTruthOracle(owned.world, owned.model)
        translator = ArduRoverCommandTranslator if kind == 'rover' else ArduPilotCommandTranslator
        runtime = SimulationRuntime(owned.profile, translator=translator(mode_ids=owned.profile.mode_ids),
            event_sink=lambda event: (log.write(json.dumps(event)+'\n'), log.flush()))
        runtime.connect()
        environment = Environment.load(ROOT/f'simulation/environments/{kind}.toml').check_safety(
            owned.profile.safety).bind(runtime.world_epoch)
        runtime.set_environment(environment.reference)
        limits = json.loads((ROOT/'simulation/scenarios/acceptance-v1.json').read_text())[kind]

        def cycle():
            start = time.monotonic()
            owned.assert_alive()
            outcome = runtime.cycle()
            if outcome.fault:
                raise RuntimeError(outcome.fault)
            world = runtime.world_snapshot()
            if world.environment != environment.reference:
                raise AssertionError('environment version not in world cut')
            truth = oracle.latest()
            if truth:
                samples.write(json.dumps({'host_ns':time.monotonic_ns(), 'truth':[truth.x_m, truth.y_m, truth.z_m],
                    'world_revision':world.version.revision, 'truth_yaw':truth.yaw_rad,
                    'state':None if world.vehicle is None or world.vehicle.reported_pose is None else [world.vehicle.reported_pose.value.position.x,world.vehicle.reported_pose.value.position.y],
                    'armed':None if world.vehicle is None else world.vehicle.operation.armed})+'\n')
                samples.flush()
            time.sleep(max(0, .1-(time.monotonic()-start)))
            return world.vehicle, truth

        until = time.monotonic()+owned.profile.warmup_ns/1e9
        while time.monotonic()<until:
            cycle()
        initial, origin = cycle()
        if initial is None or initial.reported_pose is None or origin is None:
            raise RuntimeError('fresh pose/truth required')
        origin_deadline = time.monotonic()+3
        while initial.global_position is None and time.monotonic()<origin_deadline:
            initial, _ = cycle()
        environment.validate_origin(initial)
        initial_position = initial.reported_pose.value.position
        runtime.begin_run(allow_send=True)

        def command(name, effect, phases=('COMPLETED',), timeout=12):
            result = runtime.submit_effect(effect, effect_id=name)
            if result.reason:
                raise RuntimeError(result.reason)
            until = time.monotonic()+timeout
            while time.monotonic()<until:
                cycle()
                status = runtime.effect_status(name)
                if status['phase'] in phases:
                    return status
                if status['phase'] in ('REJECTED','UNKNOWN','CANCELLED'):
                    raise RuntimeError(status)
            raise TimeoutError(name)

        command('mode', ModeEffect('GUIDED'))
        command('arm', ArmEffect())
        if kind=='copter':
            command('takeoff', TakeoffEffect(1.5), phases=('ACKNOWLEDGED','COMPLETED'))
            until=time.monotonic()+limits['takeoff_timeout_s']
            while time.monotonic()<until:
                state,truth=cycle()
                if (state and truth and state.reported_pose and
                    abs(state.reported_pose.value.position.z-initial_position.z-1.5)<=limits['takeoff_max_error_m'] and
                    abs(truth.z_m-origin.z_m-1.5)<=limits['takeoff_max_error_m']):
                    break
            else:raise TimeoutError('takeoff physical target')
        for name in ('A','HOME_AIR' if kind=='copter' else 'HOME'):
            target=environment.resolve(name)
            pose=Pose3(target.position, Quaternion(0,0,0,1))
            expected=(origin.x_m+target.position.x-initial_position.x,
                      origin.y_m+target.position.y-initial_position.y)
            until=time.monotonic()+limits['goto_timeout_s']
            if kind == 'rover':
                # A skid-steer route explicitly aligns with a bounded, already
                # validated body yaw stream before positional navigation.
                index = 0
                refresh = 0
                while time.monotonic() < until:
                    state, truth = cycle()
                    if state is None or state.reported_pose is None:
                        continue
                    current = state.reported_pose.value
                    q = current.orientation
                    yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
                    dx, dy = target.position.x-current.position.x, target.position.y-current.position.y
                    error = math.atan2(math.sin(math.atan2(dy,dx)-yaw), math.cos(math.atan2(dy,dx)-yaw))
                    if abs(error)<.15 or math.hypot(dx,dy)<.5:
                        break
                    if time.monotonic()>=refresh:
                        index += 1
                        result=runtime.submit_effect(TwistTargetEffect('base_link',
                            Twist3(Vector3(0,0,0),Vector3(0,0,max(-.35,min(.35,error)))), name+'-align'),
                            effect_id=f'{name}-align-{index}')
                        if result.reason:raise RuntimeError(result.reason)
                        refresh=time.monotonic()+.3
                else:raise TimeoutError('bounded target heading alignment')
                if index:
                    command(name+'-align-stop',StopMotionEffect(name+'-align'),timeout=limits['stop_timeout_s'])
            next_refresh=0
            sequence=0
            stable=None
            while time.monotonic()<until:
                if time.monotonic()>=next_refresh:
                    sequence+=1
                    result=runtime.submit_effect(PoseTargetEffect(target.frame,pose,name),effect_id=f'{name}-{sequence}')
                    if result.reason:raise RuntimeError(result.reason)
                    next_refresh=time.monotonic()+.3
                state,truth=cycle()
                if not state or not state.reported_pose or not truth:continue
                p=state.reported_pose.value.position
                error=math.hypot(p.x-target.position.x,p.y-target.position.y)
                truth_error=math.hypot(truth.x_m-expected[0],truth.y_m-expected[1])
                inside=error<=limits['goto_max_horizontal_error_m'] and truth_error<=limits['goto_max_horizontal_error_m']
                stable=(stable or time.monotonic()) if inside else None
                if stable and time.monotonic()-stable>=1:
                    report['targets'][name]={'state_error_m':error,'truth_error_m':truth_error,
                        'environment_generation':str(target.environment.version.generation_id)}
                    break
            else:raise TimeoutError(f'named target {name}')
            requested=time.monotonic()
            command(name+'-stop',StopMotionEffect(name),timeout=limits['stop_timeout_s'])
            stable=None
            until=requested+limits['stop_timeout_s']
            while time.monotonic()<until:
                cycle()
                speed=oracle.recent_speed_mps()
                stable=(stable or time.monotonic()) if speed is not None and speed<=limits['stop_max_horizontal_speed_mps'] else None
                if stable and time.monotonic()-stable>=limits['stop_stable_s']:break
            else:raise TimeoutError('named navigation Stop truth')
        if kind=='copter':
            command('land',LandEffect(),phases=('ACKNOWLEDGED','COMPLETED'))
            until=time.monotonic()+limits['land_timeout_s']
            while time.monotonic()<until:
                state,truth=cycle()
                if state and truth and not state.operation.armed and truth.z_m<=origin.z_m+.2:break
            else:raise TimeoutError('land physical ground')
        else:
            command('disarm',DisarmEffect())
        report['passed']=True
    except Exception as exc:
        report['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if runtime:
            try:report['stops']=runtime.shutdown()
            except Exception as exc:report['shutdown_error']=str(exc);report['passed']=False
        try:owned.close()
        except Exception as exc:report['cleanup_error']=str(exc);report['passed']=False
        log.close();samples.close()
        (directory/'summary.json').write_text(json.dumps(report,indent=2))
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--kind',choices=('copter','rover'),required=True)
    parser.add_argument('--allow-send',action='store_true')
    parser.add_argument('--run-dir',type=Path)
    args=parser.parse_args()
    if not args.allow_send:parser.error('--allow-send required')
    install_signal_cleanup()
    result=run(args.run_dir or ROOT/'artifacts/simulation'/f'environment-{args.kind}-{uuid4().hex[:8]}',args.kind)
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
