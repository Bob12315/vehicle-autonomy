"""Owned actual App + SLAM + Nav2 + Rover/Gazebo path execution acceptance."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from app.control import request
from guidance.path_following import DRIVE_OFFSET_M, PlanarBinding, drive_reference
from mapping.grid import pose_from_json
from actions.basic import yaw
from planning.models import Pose2D
from tests.simulation.launch import ROOT, OwnedSimulation, install_signal_cleanup
from tests.simulation.oracle import GazeboTruthOracle
from tests.simulation.ros2_mapping import ROOM_YAW, add_mapping_scene

CASES = ("tracking", "cancel", "map_loss", "plan_change", "timeout")


def segment_distance(x, y, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    t = max(0., min(1., ((x-a[0])*dx+(y-a[1])*dy)/max(1e-12,dx*dx+dy*dy)))
    return math.hypot(x-a[0]-t*dx,y-a[1]-t*dy)


def run(directory, case, *, autonomous=False):
    directory.mkdir(parents=True,exist_ok=False)
    os.environ["ROS_DOMAIN_ID"] = str(100+os.getpid()%100)
    owned=OwnedSimulation(directory,"rover")
    owned.manifest["ros_domain_id"]=os.environ["ROS_DOMAIN_ID"]
    owned.manifest["navigation_case"]=case
    # A denser actual sensor reduces unobserved ray gaps; unknown occupancy is
    # never filled by the harness. The pillar forces a non-straight path.
    replanning = case in ("replan","blocked","replan_cancel")
    lidar_samples=4096 if replanning else 2160
    add_mapping_scene(owned,lidar_samples=lidar_samples,pillar=(2.8,2) if replanning else (1.7,.3))
    if replanning:
        import xml.etree.ElementTree as ET
        tree=ET.parse(owned.world_path)
        ET.SubElement(tree.find('world'),'plugin',filename='gz-sim-user-commands-system',name='gz::sim::systems::UserCommands')
        tree.write(owned.world_path)
    endpoint=directory/"app.sock"
    exchange=directory/"exchange";exchange.mkdir()
    mapping=directory/"mapping.toml"
    mapping.write_text(f'schema=1\ndirectory="{exchange}"\nclock_domain_id="host-monotonic-simulation"\nmax_age_ns=10000000000\n')
    plan=directory/"plan.json"
    config=directory/"navigation.toml"
    config.write_text(f'schema=1\nmodel="target_rover_front_axle_v1"\nplan_path="{plan}"\ntimeout_ns={10_000_000_000 if case=="timeout" else 70_000_000_000}\n')
    if replanning:config.write_text(config.read_text()+'tracking_mode="stop_turn"\n')
    if autonomous:
        goals=directory/"goals.toml"
        goals.write_text('schema=1\nenvironment_id="environment:rover-training-v1"\n[[goals]]\nname="POINT_A"\nframe="odom"\nreference_point="navigation_reference"\nposition=[0.8,2.0]\n')
        if replanning:
            goals.write_text(goals.read_text().replace("[[goals]]", "[policy]\nmax_replans=1\nretry_delay_s=2\nplanning_reserve_m=0.1\n[[goals]]").replace("[0.8,2.0]","[0.4,2.5]"))
        if case == "unreachable":goals.write_text(goals.read_text().replace('[0.8,2.0]','[2.8,0.0]'))
        config.write_text(config.read_text()+f'goals_path="{goals}"\n')
    profile=directory/"profile.toml"
    profile.write_text((ROOT/"simulation/profiles/rover.toml").read_text().replace("port = 5760",f"port = {owned.port}"))
    bridge=directory/"bridge.yaml"
    bridge.write_text(f'''- ros_topic_name: /clock
  gz_topic_name: /world/{owned.world}/clock
  ros_type_name: rosgraph_msgs/msg/Clock
  gz_type_name: gz.msgs.Clock
  direction: GZ_TO_ROS
- ros_topic_name: /scan_raw
  gz_topic_name: /vaf/lidar
  ros_type_name: sensor_msgs/msg/LaserScan
  gz_type_name: gz.msgs.LaserScan
  direction: GZ_TO_ROS
''')
    wrapper=str(ROOT/"scripts/with_ros2.sh")
    evidence=(directory/"status.jsonl").open("w")
    report={"passed":False,"case":case,"lidar_rays":lidar_samples,"room_yaw_rad":ROOM_YAW}
    slam_parameters=ROOT/"simulation/mapping/slam_toolbox.yaml"
    if replanning:
        slam_parameters=directory/'slam_toolbox.yaml'
        slam_parameters.write_text((ROOT/'simulation/mapping/slam_toolbox.yaml').read_text()+'    use_scan_matching: false\n')
        report['map_alignment']='telemetry_odometry; scan matching explicitly disabled for changing scene'
    trajectory=[]

    def status():
        owned.assert_alive()
        response=request(endpoint,"status")
        if not response["ok"]:raise RuntimeError(response)
        s=response["result"];t=oracle.latest()
        if t is None or (s["motion_warmup_remaining_ns"] == 0 and time.monotonic_ns()-t.host_received_ns>1_000_000_000):
            raise RuntimeError("fresh independent Gazebo truth required")
        evidence.write(json.dumps({"host_ns":time.monotonic_ns(),"status":s,
            "truth":[t.x_m,t.y_m,t.yaw_rad],"truth_speed":oracle.recent_speed_mps()})+"\n");evidence.flush()
        return s,t

    def wait(predicate, seconds, label):
        until=time.monotonic()+seconds;last=None
        while time.monotonic()<until:
            if endpoint.exists() and oracle.latest() is not None:
                last,_=status()
                if predicate(last):return last
            else:owned.assert_alive()
            time.sleep(.1)
        raise TimeoutError(f"{label}: {last}")

    def lifecycle(transition):
        p=owned.start_process("slam_"+transition,[wrapper,"ros2","lifecycle","set","--no-daemon","/slam_toolbox",transition])
        try:code=p.wait(timeout=25)
        finally:owned.stop_process(p)
        if code:raise RuntimeError("SLAM lifecycle failed: "+transition)

    try:
        flags=[] if os.environ.get("DISPLAY") else ["--headless-rendering"]
        owned.start_process("gazebo",["gz","sim","-s","-r",*flags,"-v3",str(owned.world_path)])
        owned.start_sitl()
        oracle=GazeboTruthOracle(owned.world,owned.model)
        app=owned.start_process("application",[sys.executable,"-m","app.main","run","--profile","rover_sim",
            "--config",str(profile),"--control-socket",str(endpoint),"--ros2-mapping-config",str(mapping),
            "--navigation-config",str(config),"--allow-send"])
        owned.start_process("gz_bridge",[wrapper,sys.executable,"-m","integrations.ros2.run","ros_gz_bridge","parameter_bridge",
            "--ros-args","-p",f"config_file:={bridge}"])
        sidecar=owned.start_process("mapping_sidecar",[wrapper,sys.executable,"-m","integrations.ros2.mapping_node",
            "--config",str(mapping),"--control-socket",str(endpoint)])
        owned.start_process("slam",[wrapper,sys.executable,"-m","integrations.ros2.run","slam_toolbox","async_slam_toolbox_node",
            "--ros-args","--params-file",str(slam_parameters)])
        lifecycle("configure");lifecycle("activate")
        ready=wait(lambda s:s["state"]=="READY" and s["mapping"]["adopted"] and s["mapping"]["age_ns"]<1_000_000_000
                   and s["environment"]["origin_verified"] and s["motion_warmup_remaining_ns"]==0,75,"navigation preflight")
        if ready["system_send"] or ready["action_send"] or ready["vehicle"]["armed"]:
            raise AssertionError("idle Application retained authority")
        if autonomous and case in ("planning_cancel","unreachable"):
            before=oracle.latest()
            response=request(endpoint,"start",{"mission":"navigate:POINT_A"})
            if not response["ok"]:raise RuntimeError(response)
            if case == "planning_cancel":
                if not request(endpoint,"cancel")["ok"]:raise AssertionError("planning cancel rejected")
            final=wait(lambda s:s['task']['status'] in ('FAILED','CANCELLED','SUCCEEDED'),25,'planning terminal')
            expected='CANCELLED' if case=='planning_cancel' else 'FAILED'
            after=oracle.latest()
            if (final['task']['status']!=expected or final['vehicle']['armed'] or final['system_send']
                    or final['action_send'] or final['task']['effects']
                    or math.hypot(after.x_m-before.x_m,after.y_m-before.y_m)>.02):
                raise AssertionError('planning-only scenario moved or retained authority')
            manifests=list(directory.glob('navigation-jobs/*/*/*/manifest.json'))
            if any(not json.loads(p.read_text())['process_group_released'] for p in manifests):
                raise AssertionError('cancelled planning left a native group')
            report.update(task=final['task'],native_jobs=len(manifests),planning_only=True)
            if not request(endpoint,'shutdown')['ok'] or app.wait(timeout=12):raise AssertionError('shutdown failed')
            owned.stop_process(app);report['passed']=True
            return report
        transform=pose_from_json(ready["mapping"]["odom_in_map"])
        binding=PlanarBinding(transform.position.x,transform.position.y,yaw(transform))
        position=ready["vehicle"]["pose"]["position"]
        q=ready["vehicle"]["pose"]["orientation_xyzw"]
        heading=math.atan2(2*(q[3]*q[2]+q[0]*q[1]),1-2*(q[1]*q[1]+q[2]*q[2]))
        start=binding.to_map(drive_reference(Pose2D(position[0],position[1],heading)))
        goal=binding.to_map(Pose2D(.8,2.0))
        command=[sys.executable,"-m","app.plan","--mapping-config",str(mapping),"--control-socket",str(endpoint),
            "--start",f"{start.x:.9f}",f"{start.y:.9f}","--goal",f"{goal.x:.9f}",f"{goal.y:.9f}","--clearance",".95",
            "--output",str(plan),"--evidence-directory",str(directory/"nav2")]
        origin=oracle.latest()
        initial=ready["vehicle"]["pose"]["position"]
        if autonomous:
            response=request(endpoint,"start",{"mission":"navigate:POINT_A"})
            if not response["ok"]:raise RuntimeError(response)
            wait(lambda s:s["task"]["status"] in ("RUNNING","FAILED","CANCELLED"),25,"Application planning")
            if not plan.exists():raise AssertionError("Application returned no admitted plan")
            value=json.loads(plan.read_text())
            (directory/"planning.log").write_text(json.dumps(value)+'\n')
            d=value["result"]
        else:
            result=subprocess.run(command,capture_output=True,text=True,timeout=25)
            (directory/"planning.log").write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError("live Nav2 planning failed: "+result.stdout)
            d=json.loads(result.stdout)["result"]
            response=request(endpoint,"start",{"mission":"follow_path"})
        report["plan"]={"request_id":d["request_id"],"length_m":d["length_m"],"poses":len(d["poses"]),"clearance_m":d["clearance_m"]}
        if d["executable"]:raise AssertionError("planner granted authority")
        if not response["ok"]:raise RuntimeError(response)
        report["task_id"]=response["result"]["task_id"]
        submitted_ns=time.monotonic_ns();trigger_ns=None;moving_seen=False;terminal_ns=None;stable=None;recovery_stop_ns=None;replan_cancelled=False
        until=time.monotonic()+110
        while time.monotonic()<until:
            s,t=status()
            # Oracle is a passive measurement only; never used by production
            # guidance, Nav2 or SLAM input.
            ox,oy=t.x_m-origin.x_m+initial[0],t.y_m-origin.y_m+initial[1]
            trajectory.append((time.monotonic_ns(),ox,oy,oracle.recent_speed_mps(),t.yaw_rad))
            speed=oracle.recent_speed_mps()
            yaw_rate=oracle.recent_yaw_rate_rad_s()
            physical_motion=speed is not None and speed>(.01 if replanning else .06)
            if case=='timeout' and yaw_rate is not None and abs(yaw_rate)>.08:physical_motion=True
            if s["task"]["step"]=="follow_path" and physical_motion:
                moving_seen=True
                if trigger_ns is None and case in ("cancel","map_loss","plan_change"):
                    trigger_ns=time.monotonic_ns()
                    if case=="cancel":
                        if not request(endpoint,"cancel")["ok"]:raise AssertionError("cancel rejected")
                    elif case=="map_loss":owned.stop_process(sidecar)
                    else:plan.write_text("{}")
            if replanning and trigger_ns is None and moving_seen:
                from tests.simulation.object_fixture import service
                if case != "blocked":
                    original=[binding.to_odom(Pose2D(*v)) for v in d['poses']]
                    affected=min(original,key=lambda v:abs(v.y-1.25))
                    x,y,width=affected.x-.95,affected.y,.12
                else:x,y,width=0,1.25,7.5
                report['new_obstacle']=[x,y,width,.12]
                model=f'<sdf version="1.9"><model name="new_obstacle"><static>true</static><pose>{x} {y} 0.75 0 0 0</pose><link name="box"><collision name="collision"><geometry><box><size>{width} .12 1.5</size></box></geometry></collision><visual name="visual"><geometry><box><size>{width} .12 1.5</size></box></geometry></visual></link></model></sdf>'
                service(owned,'create','gz.msgs.EntityFactory','sdf: '+json.dumps(model))
                trigger_ns=time.monotonic_ns()
            task=s["task"]
            if replanning and task['history'] and recovery_stop_ns is None:
                recovery_stop_ns=time.monotonic_ns()
                if speed is None or speed>.1 or yaw_rate is None or abs(yaw_rate)>.15:
                    raise AssertionError('recovery started without observed linear/angular stop')
            if case=='replan_cancel' and task['attempt']==2 and task['status']=='PLANNING' and not replan_cancelled:
                if not request(endpoint,'cancel')['ok']:raise AssertionError('replan cancel rejected')
                replan_cancelled=True
            if task["status"] in ("FAILED","CANCELLED","SUCCEEDED"):
                if terminal_ns is None:terminal_ns=time.monotonic_ns()
                if not moving_seen:raise AssertionError("no actual movement before terminal result")
                expected="SUCCEEDED" if case in ("tracking","replan") else "CANCELLED" if case in ("cancel","replan_cancel") else "FAILED"
                if task["status"]!=expected:
                    raise AssertionError(f"unexpected task result: {task['status']}: {task['error']}; {task['steps']}")
                if s["system_send"] or s["action_send"]:raise AssertionError("terminal retained SEND")
                if speed is None or speed>.10 or yaw_rate is None or abs(yaw_rate)>.15:
                    raise AssertionError("terminal not physically stopped")
                stable=stable or time.monotonic()
                if time.monotonic()-stable>=2:
                    (directory/"final-task.json").write_text(json.dumps(task,indent=2))
                    report["task"]={key:task[key] for key in ("task_id","mission","configuration_sha256","status","step","error","steps","stops")}
                    report["effect_count"]=len(task["effects"])
                    report["stop_speed_mps"]=speed
                    report["stop_yaw_rate_rps"]=yaw_rate
                    report["navigation"]=s["navigation"]
                    break
            else:stable=None
            time.sleep(.1)
        else:raise TimeoutError("physical navigation did not terminate")
        report["duration_s"]=(terminal_ns-submitted_ns)/1e9
        # Reconstruct the exact pinned binding emitted by the admission, not
        # the slightly older status sampled before the external planner ran.
        events=[json.loads(line) for line in (directory/"application.log").read_text().splitlines() if line.startswith('{')]
        admissions=[e for e in events if e.get("event")=="navigation_admitted"]
        admission=admissions[-1]
        points=admission["odom_poses"]
        cross=max(min(segment_distance(x+DRIVE_OFFSET_M*math.cos(yaw),y+DRIVE_OFFSET_M*math.sin(yaw),a,b)
                  for adm in admissions for a,b in zip(adm["odom_poses"],adm["odom_poses"][1:])) for _,x,y,_,yaw in trajectory)
        report["truth_max_cross_track_m"]=cross
        # Independent physical obstacle geometry in the rotated room.
        clearance=[]
        for _,x,y,_,_ in trajectory:
            px=math.cos(ROOM_YAW)*x+math.sin(ROOM_YAW)*y
            py=-math.sin(ROOM_YAW)*x+math.cos(ROOM_YAW)*y
            clearance.append(math.hypot(max(abs(px-(2.8 if replanning else 1.7))-.2,0),max(abs(py-(2 if replanning else .3))-.2,0)))
        report["truth_min_pillar_clearance_m"]=min(clearance)
        if cross>.3 or min(clearance)<.51:raise AssertionError("independent path/physical clearance exceeded")
        if case in ("tracking","replan"):
            final=trajectory[-1]
            error=math.hypot(final[1]+DRIVE_OFFSET_M*math.cos(final[4])-points[-1][0],
                             final[2]+DRIVE_OFFSET_M*math.sin(final[4])-points[-1][1])
            report["truth_goal_error_m"]=error
            if error>.75 or s["vehicle"]["armed"]:raise AssertionError("arrival/disarm failed")
            direct=segment_distance(1.7*math.cos(ROOM_YAW)-.3*math.sin(ROOM_YAW),
                1.7*math.sin(ROOM_YAW)+.3*math.cos(ROOM_YAW),points[0],points[-1])
            report["direct_line_pillar_center_distance_m"]=direct
            detour=max(segment_distance(p[0],p[1],points[0],points[-1]) for p in points)
            report["planned_detour_from_direct_line_m"]=detour
            if not replanning and detour<.15:raise AssertionError("scene did not require a route detour")
        if trigger_ns is not None:
            # Use first terminal cut, not the extra two seconds used by this
            # oracle, for the original eight-second stopping requirement.
            report["fault_to_confirmed_stop_s"]=((recovery_stop_ns if replanning else terminal_ns)-trigger_ns)/1e9
            if report["fault_to_confirmed_stop_s"]>8:raise AssertionError("stop exceeded original eight seconds")
        if case=="timeout" and not any("deadline" in (step["error"] or "") for step in report["task"]["steps"]):
            raise AssertionError("timeout was not the cause of failure")
        if replanning:
            report['attempt']=s['task']['attempt'];report['history']=s['task']['history']
            hard_map_fault = case=='blocked' and s['task']['attempt']==1 and s['task']['error']=='navigation_alignment_changed'
            if hard_map_fault:report['nonrecoverable_alignment_stop']=True
            elif s['task']['attempt'] != 2 or recovery_stop_ns is None:raise AssertionError('replan did not follow confirmed stop/recovery')
            if case=='replan_cancel' and not replan_cancelled:raise AssertionError('did not cancel during second plan')
            if case=='replan' and len(admissions)!=2:raise AssertionError('new route did not pass independent admission')
        if case not in ("tracking","replan"):

            recovery=request(endpoint,"start",{"mission":"safe_recovery"})
            if not recovery["ok"]:raise RuntimeError(recovery)
            recovered=wait(lambda s:s["task"]["status"] in ("SUCCEEDED","FAILED"),25,"explicit recovery")
            if recovered["task"]["status"]!="SUCCEEDED" or recovered["vehicle"]["armed"]:
                raise AssertionError("explicit recovery failed")
            report["recovery_disarmed"]=True
        if not request(endpoint,"shutdown")["ok"] or app.wait(timeout=12) or endpoint.exists():
            raise AssertionError("application shutdown failed")
        owned.stop_process(app)
        jobs=[json.loads(p.read_text()) for p in directory.glob('navigation-jobs/*/*/*/manifest.json')]
        if any(not j['process_group_released'] for j in jobs):raise AssertionError('native planning group not released')
        report['native_jobs_released']=len(jobs)
        report["passed"]=True
    except Exception as exc:
        report["error"]=f"{type(exc).__name__}: {exc}"
    finally:
        try:owned.close()
        except Exception as exc:report["cleanup_error"]=str(exc);report["passed"]=False
        evidence.close()
        (directory/"trajectory.json").write_text(json.dumps(trajectory))
        (directory/"summary.json").write_text(json.dumps(report,indent=2))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-send",action="store_true")
    parser.add_argument("--case",choices=CASES,default="tracking")
    parser.add_argument("--run-dir",type=Path)
    args=parser.parse_args()
    if not args.allow_send:parser.error("explicit --allow-send required for simulated motion")
    install_signal_cleanup()
    directory=(args.run_dir or ROOT/"artifacts/simulation"/f"path-{args.case}-{uuid4().hex[:8]}").resolve()
    report=run(directory,args.case)
    print(json.dumps({"directory":str(directory),**report}))
    return 0 if report["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
