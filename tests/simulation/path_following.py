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


def run(directory, case):
    directory.mkdir(parents=True,exist_ok=False)
    os.environ["ROS_DOMAIN_ID"] = str(100+os.getpid()%100)
    owned=OwnedSimulation(directory,"rover")
    owned.manifest["ros_domain_id"]=os.environ["ROS_DOMAIN_ID"]
    owned.manifest["navigation_case"]=case
    # A denser actual sensor reduces unobserved ray gaps; unknown occupancy is
    # never filled by the harness. The pillar forces a non-straight path.
    add_mapping_scene(owned,lidar_samples=2160,pillar=(1.7,.3))
    endpoint=directory/"app.sock"
    exchange=directory/"exchange";exchange.mkdir()
    mapping=directory/"mapping.toml"
    mapping.write_text(f'schema=1\ndirectory="{exchange}"\nclock_domain_id="host-monotonic-simulation"\nmax_age_ns=10000000000\n')
    plan=directory/"plan.json"
    config=directory/"navigation.toml"
    config.write_text(f'schema=1\nmodel="target_rover_front_axle_v1"\nplan_path="{plan}"\ntimeout_ns={10_000_000_000 if case=="timeout" else 70_000_000_000}\n')
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
    report={"passed":False,"case":case,"lidar_rays":2160,"room_yaw_rad":ROOM_YAW}
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
            "--ros-args","--params-file",str(ROOT/"simulation/mapping/slam_toolbox.yaml")])
        lifecycle("configure");lifecycle("activate")
        ready=wait(lambda s:s["state"]=="READY" and s["mapping"]["adopted"] and s["mapping"]["age_ns"]<1_000_000_000
                   and s["environment"]["origin_verified"] and s["motion_warmup_remaining_ns"]==0,75,"navigation preflight")
        if ready["system_send"] or ready["action_send"] or ready["vehicle"]["armed"]:
            raise AssertionError("idle Application retained authority")
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
        result=subprocess.run(command,capture_output=True,text=True,timeout=25)
        (directory/"planning.log").write_text(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError("live Nav2 planning failed: "+result.stdout)
        d=json.loads(result.stdout)["result"]
        report["plan"]={"request_id":d["request_id"],"length_m":d["length_m"],"poses":len(d["poses"]),"clearance_m":d["clearance_m"]}
        if d["executable"]:raise AssertionError("planner granted authority")
        origin=oracle.latest()
        initial=status()[0]["vehicle"]["pose"]["position"]
        response=request(endpoint,"start",{"mission":"follow_path"})
        if not response["ok"]:raise RuntimeError(response)
        report["task_id"]=response["result"]["task_id"]
        submitted_ns=time.monotonic_ns();trigger_ns=None;moving_seen=False;terminal_ns=None;stable=None
        until=time.monotonic()+110
        while time.monotonic()<until:
            s,t=status()
            # Oracle is a passive measurement only; never used by production
            # guidance, Nav2 or SLAM input.
            ox,oy=t.x_m-origin.x_m+initial[0],t.y_m-origin.y_m+initial[1]
            trajectory.append((time.monotonic_ns(),ox,oy,oracle.recent_speed_mps(),t.yaw_rad))
            speed=oracle.recent_speed_mps()
            if s["task"]["step"]=="follow_path" and speed is not None and speed>.06:
                moving_seen=True
                if trigger_ns is None and case in ("cancel","map_loss","plan_change"):
                    trigger_ns=time.monotonic_ns()
                    if case=="cancel":
                        if not request(endpoint,"cancel")["ok"]:raise AssertionError("cancel rejected")
                    elif case=="map_loss":owned.stop_process(sidecar)
                    else:plan.write_text("{}")
            task=s["task"]
            if task["status"] in ("FAILED","CANCELLED","SUCCEEDED"):
                if terminal_ns is None:terminal_ns=time.monotonic_ns()
                if not moving_seen:raise AssertionError("no actual movement before terminal result")
                expected="SUCCEEDED" if case=="tracking" else "CANCELLED" if case=="cancel" else "FAILED"
                if task["status"]!=expected:
                    raise AssertionError(f"unexpected task result: {task['status']}: {task['error']}; {task['steps']}")
                if s["system_send"] or s["action_send"]:raise AssertionError("terminal retained SEND")
                if speed is None or speed>.10:raise AssertionError("terminal not physically stopped")
                stable=stable or time.monotonic()
                if time.monotonic()-stable>=2:
                    (directory/"final-task.json").write_text(json.dumps(task,indent=2))
                    report["task"]={key:task[key] for key in ("task_id","mission","configuration_sha256","status","step","error","steps","stops")}
                    report["effect_count"]=len(task["effects"])
                    report["stop_speed_mps"]=speed
                    report["navigation"]=s["navigation"]
                    break
            else:stable=None
            time.sleep(.1)
        else:raise TimeoutError("physical navigation did not terminate")
        report["duration_s"]=(terminal_ns-submitted_ns)/1e9
        # Reconstruct the exact pinned binding emitted by the admission, not
        # the slightly older status sampled before the external planner ran.
        events=[json.loads(line) for line in (directory/"application.log").read_text().splitlines() if line.startswith('{')]
        admission=next(e for e in events if e.get("event")=="navigation_admitted")
        points=admission["odom_poses"]
        cross=max(min(segment_distance(x+DRIVE_OFFSET_M*math.cos(yaw),y+DRIVE_OFFSET_M*math.sin(yaw),a,b)
                  for a,b in zip(points,points[1:])) for _,x,y,_,yaw in trajectory)
        report["truth_max_cross_track_m"]=cross
        # Independent physical obstacle geometry in the rotated room.
        clearance=[]
        for _,x,y,_,_ in trajectory:
            px=math.cos(ROOM_YAW)*x+math.sin(ROOM_YAW)*y
            py=-math.sin(ROOM_YAW)*x+math.cos(ROOM_YAW)*y
            clearance.append(math.hypot(max(abs(px-1.7)-.2,0),max(abs(py-.3)-.2,0)))
        report["truth_min_pillar_clearance_m"]=min(clearance)
        if cross>.3 or min(clearance)<.51:raise AssertionError("independent path/physical clearance exceeded")
        if case=="tracking":
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
            if detour<.15:raise AssertionError("scene did not require a route detour")
        if trigger_ns is not None:
            # Use first terminal cut, not the extra two seconds used by this
            # oracle, for the original eight-second stopping requirement.
            report["fault_to_confirmed_stop_s"]=(terminal_ns-trigger_ns)/1e9
            if report["fault_to_confirmed_stop_s"]>8:raise AssertionError("stop exceeded original eight seconds")
        if case=="timeout" and not any("deadline" in (step["error"] or "") for step in report["task"]["steps"]):
            raise AssertionError("timeout was not the cause of failure")
        if case!="tracking":
            recovery=request(endpoint,"start",{"mission":"safe_recovery"})
            if not recovery["ok"]:raise RuntimeError(recovery)
            recovered=wait(lambda s:s["task"]["status"] in ("SUCCEEDED","FAILED"),25,"explicit recovery")
            if recovered["task"]["status"]!="SUCCEEDED" or recovered["vehicle"]["armed"]:
                raise AssertionError("explicit recovery failed")
            report["recovery_disarmed"]=True
        if not request(endpoint,"shutdown")["ok"] or app.wait(timeout=12) or endpoint.exists():
            raise AssertionError("application shutdown failed")
        owned.stop_process(app)
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
