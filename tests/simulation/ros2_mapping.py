"""Actual Rover/App/SLAM Toolbox mapping, independent truth and map reload."""
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
import xml.etree.ElementTree as ET

from app.control import request
from environments.resources import Environment
from mapping.grid import MapStore, pose_from_json
from core.transform import rotate_vector
from contracts.core.geometry import Quaternion, Vector3
from tests.simulation.launch import ROOT, OwnedSimulation, install_signal_cleanup
from tests.simulation.oracle import GazeboTruthOracle


ROOM_YAW = .15  # Avoid the upstream axis-aligned occupancy-boundary defect #689.


def add_mapping_scene(owned, *, lidar_samples=720, pillar=(2.8, 2), room_yaw=None):
    room_yaw=ROOM_YAW if room_yaw is None else room_yaw
    model = ET.parse(owned.model_path)
    model.find("model/link[@name='base_link']").append(ET.fromstring(f'''
      <sensor name="mapping_lidar" type="gpu_lidar">
        <pose>0 0 0.2 0 0 0</pose><topic>/vaf/lidar</topic>
        <always_on>true</always_on><update_rate>10</update_rate>
        <lidar><scan><horizontal><samples>{lidar_samples}</samples><resolution>1</resolution>
          <min_angle>-3.14159265359</min_angle><max_angle>3.14159265359</max_angle>
        </horizontal></scan><range><min>0.15</min><max>12</max><resolution>0.01</resolution></range>
        <noise><type>gaussian</type><mean>0</mean><stddev>0.005</stddev></noise></lidar>
      </sensor>'''))
    model.write(owned.model_path)
    world = ET.parse(owned.world_path)
    world.find("world").append(ET.fromstring('''<plugin filename="gz-sim-sensors-system"
       name="gz::sim::systems::Sensors"><render_engine>ogre2</render_engine></plugin>'''))
    walls = (("east", 4, 0, .2, 8), ("west", -4, 0, .2, 8),
             ("north", 0, 4, 8, .2), ("south", 0, -4, 8, .2),
             ("pillar", *pillar, .4, .4))
    for name, x, y, width, height in walls:
        x, y = x * math.cos(room_yaw) - y * math.sin(room_yaw), x * math.sin(room_yaw) + y * math.cos(room_yaw)
        geometry = f"<geometry><box><size>{width} {height} 1.5</size></box></geometry>"
        world.find("world").append(ET.fromstring(f'''<model name="mapping_{name}"><static>true</static>
          <pose>{x} {y} 0.75 0 0 {room_yaw}</pose><link name="obstacle">
          <collision name="collision">{geometry}</collision><visual name="visual">{geometry}</visual>
          </link></model>'''))
    world.write(owned.world_path)


def map_metrics(grid, transform):
    # Scene geometry is independent of the SLAM estimate and sensor adapter.
    odom_in_map = pose_from_json(transform)
    inverse_origin = Quaternion(-grid.origin.orientation.x, -grid.origin.orientation.y,
                                -grid.origin.orientation.z, grid.origin.orientation.w)
    walls = []
    for x, y in ((3.9, 0), (-3.9, 0), (0, 3.9), (0, -3.9)):
        x, y = x * math.cos(ROOM_YAW) - y * math.sin(ROOM_YAW), x * math.sin(ROOM_YAW) + y * math.cos(ROOM_YAW)
        p = rotate_vector(odom_in_map.orientation, Vector3(x, y, 0))
        p = Vector3(p.x + odom_in_map.position.x - grid.origin.position.x,
                    p.y + odom_in_map.position.y - grid.origin.position.y, 0)
        p = rotate_vector(inverse_origin, p)
        ix, iy = int(math.floor(p.x / grid.resolution_m)), int(math.floor(p.y / grid.resolution_m))
        nearby = [grid.cells[j * grid.width + i] for j in range(max(0, iy-3), min(grid.height, iy+4))
                  for i in range(max(0, ix-3), min(grid.width, ix+4))]
        walls.append(bool(nearby and max(nearby) >= 65))
    return {"width": grid.width, "height": grid.height, "resolution_m": grid.resolution_m,
            "known": sum(v >= 0 for v in grid.cells), "occupied": sum(v >= 65 for v in grid.cells),
            "wall_matches": walls}


def run(directory, *, smoke=False, planning_probe=None):
    directory.mkdir(parents=True, exist_ok=False)
    os.environ["ROS_DOMAIN_ID"] = str(100 + (os.getpid() % 100))
    owned = OwnedSimulation(directory, "rover")
    owned.manifest["ros_domain_id"] = os.environ["ROS_DOMAIN_ID"]
    add_mapping_scene(owned)
    report = {"passed": False, "smoke_only": smoke, "room_yaw_rad": ROOM_YAW, "steps": {}}
    endpoint = directory / "app.sock"
    exchange = directory / "exchange"
    exchange.mkdir()
    config = directory / "mapping.toml"
    config.write_text(f'schema = 1\ndirectory = "{exchange}"\nclock_domain_id = "host-monotonic-simulation"\nmax_age_ns = 10000000000\n')
    profile = directory / "profile.toml"
    profile.write_text((ROOT / "simulation/profiles/rover.toml").read_text().replace("port = 5760", f"port = {owned.port}"))
    bridge = directory / "bridge.yaml"
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
    evidence = (directory / "application-status.jsonl").open("w")
    wrapper = str(ROOT / "scripts/with_ros2.sh")

    def ros_command(label, *arguments):
        process = owned.start_process(label, [wrapper, "ros2", *arguments])
        try:
            result = process.wait(timeout=25)
        except subprocess.TimeoutExpired:
            owned.stop_process(process)
            raise TimeoutError(f"ROS command {label} timed out")
        owned.stop_process(process)
        if result:
            raise RuntimeError(f"ROS command {label} exited {result}")

    def start_slam(label):
        process = owned.start_process(label, [wrapper, sys.executable, "-m", "integrations.ros2.run", "slam_toolbox", "async_slam_toolbox_node",
            "--ros-args", "--params-file", str(ROOT / "simulation/mapping/slam_toolbox.yaml")])
        ros_command(label + "_configure", "lifecycle", "set", "--no-daemon", "/slam_toolbox", "configure")
        return process

    def status():
        owned.assert_alive()
        response = request(endpoint, "status")
        if not response["ok"]:
            raise RuntimeError(response)
        value = response["result"]
        truth = oracle.latest()
        if truth and value["state"] in ("READY", "RUNNING_TASK") and time.monotonic_ns() - truth.host_received_ns > 1_000_000_000:
            raise RuntimeError("independent Gazebo truth stale")
        evidence.write(json.dumps({"host_ns": time.monotonic_ns(), "status": value,
            "truth": None if truth is None else [truth.x_m, truth.y_m, truth.yaw_rad],
            "truth_speed": oracle.recent_speed_mps()}) + "\n")
        evidence.flush()
        return value, truth

    def wait_for(predicate, timeout, description):
        last = None
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if endpoint.exists():
                last, _ = status()
                if predicate(last):
                    return last
            else:
                owned.assert_alive()
            time.sleep(.2)
        raise TimeoutError(f"{description}: {last}")

    try:
        renderer_flags = [] if os.environ.get("DISPLAY") else ["--headless-rendering"]
        owned.manifest["renderer"] = "GLX server-only" if not renderer_flags else "EGL headless"
        owned.start_process("gazebo", ["gz", "sim", "-s", "-r", *renderer_flags, "-v3", str(owned.world_path)])
        owned.start_sitl()
        oracle = GazeboTruthOracle(owned.world, owned.model)
        app = owned.start_process("application", [sys.executable, "-m", "app.main", "run", "--profile", "rover_sim",
            "--config", str(profile), "--control-socket", str(endpoint), "--ros2-mapping-config", str(config),
            *([] if smoke else ["--allow-send"])])
        owned.start_process("gz_bridge", [wrapper, sys.executable, "-m", "integrations.ros2.run", "ros_gz_bridge", "parameter_bridge",
            "--ros-args", "-p", f"config_file:={bridge}"])
        sidecar = owned.start_process("mapping_sidecar", [wrapper, sys.executable, "-m", "integrations.ros2.mapping_node",
            "--config", str(config), "--control-socket", str(endpoint)])
        slam = start_slam("slam")
        ros_command("slam_activate", "lifecycle", "set", "--no-daemon", "/slam_toolbox", "activate")
        ready = wait_for(lambda s: s["mapping"]["adopted"], 45, "actual SLAM map")
        store = MapStore(exchange / "maps")
        digest = ready["mapping"]["sha256"]
        grid = store.load(digest)
        report["initial_map"] = map_metrics(grid, ready["mapping"]["odom_in_map"])
        if report["initial_map"]["known"] < 500 or report["initial_map"]["occupied"] < 100 or not all(report["initial_map"]["wall_matches"]):
            raise RuntimeError(f"independent scene geometry not represented: {report['initial_map']}")
        store.export_pgm(digest, directory / "export")
        report["export_roundtrip"] = store.load(digest) == grid
        if planning_probe is not None:
            report["readonly_planning"] = planning_probe(endpoint, config, directory)
        if not smoke:
            ready = wait_for(lambda s: s["state"] == "READY" and s["environment"]["origin_verified"]
                and s["motion_warmup_remaining_ns"] == 0 and s["mapping"]["adopted"], 60, "motion preflight")
            origin = oracle.latest()
            initial_pose = ready["vehicle"]["pose"]["position"]
            environment = Environment.load(ROOT / "simulation/environments/rover.toml").bind(ready["world_version"]["generation"])
            cli = subprocess.run([sys.executable, "-m", "app.main", "ctl", "--profile", "rover_sim",
                "--control-socket", str(endpoint), "start", "--mission", "basic_route"], capture_output=True, text=True, timeout=4)
            if cli.returncode:
                raise RuntimeError(cli.stdout)
            report["task_id"] = json.loads(cli.stdout)["result"]["task_id"]
            until = time.monotonic() + 220
            while time.monotonic() < until:
                state, truth = status()
                task = state["task"]
                if task["status"] in ("FAILED", "CANCELLED"):
                    raise RuntimeError(f"Mission {task['status']}: {task['error']}")
                for step in task["steps"]:
                    name = step["step"]
                    if name in report["steps"]:
                        continue
                    if step["reason"] != "SUCCEEDED" or truth is None:
                        raise RuntimeError(f"step {name} has no physical evidence")
                    metric = {"truth": [truth.x_m, truth.y_m], "reason": step["reason"]}
                    if name in ("goto_a", "goto_b", "home"):
                        target = environment.resolve({"goto_a": "A", "goto_b": "B", "home": "HOME"}[name]).position
                        error = math.hypot(truth.x_m - (origin.x_m + target.x - initial_pose[0]),
                                           truth.y_m - (origin.y_m + target.y - initial_pose[1]))
                        metric["truth_error_m"] = error
                        if error > .75:
                            raise RuntimeError(f"{name} exceeds original navigation tolerance")
                    if name in ("goto_a", "goto_b", "home", "stop"):
                        speed = oracle.recent_speed_mps()
                        if speed is None or speed > .10:
                            raise RuntimeError(f"{name} stop speed {speed}")
                        metric["truth_speed_mps"] = speed
                    report["steps"][name] = metric
                if task["status"] == "SUCCEEDED":
                    if state["system_send"] or state["action_send"] or state["vehicle"]["armed"]:
                        raise RuntimeError("mission ended with authority or armed state")
                    break
                time.sleep(.2)
            else:
                raise TimeoutError("mapping Mission deadline")
            mapped = wait_for(lambda s: s["mapping"]["adopted"], 10, "final map")
            report["final_map"] = map_metrics(store.load(mapped["mapping"]["sha256"]), mapped["mapping"]["odom_in_map"])
            if not all(report["final_map"]["wall_matches"]):
                raise RuntimeError("moving map lost the independently specified walls")
            store.export_pgm(mapped["mapping"]["sha256"], directory / "final-export")
            ros_command("serialize", "service", "call", "/slam_toolbox/serialize_map", "slam_toolbox/srv/SerializePoseGraph",
                json.dumps({"filename": str(directory / "saved_graph")}))
            if not (directory / "saved_graph.posegraph").is_file() or not (directory / "saved_graph.data").is_file():
                raise RuntimeError("SLAM graph was not saved")
            old_source = mapped["mapping"]["source_epoch"]
            owned.stop_process(slam)
            wait_for(lambda s: not s["mapping"]["adopted"], 12, "stopped SLAM invalidates map")
            slam = start_slam("slam_reload")
            ros_command("reload_activate", "lifecycle", "set", "--no-daemon", "/slam_toolbox", "activate")
            load_request_ns = time.monotonic_ns()
            ros_command("deserialize", "service", "call", "/slam_toolbox/deserialize_map", "slam_toolbox/srv/DeserializePoseGraph",
                json.dumps({"filename": str(directory / "saved_graph"), "match_type": 1,
                            "initial_pose": {"x": 0.0, "y": 0.0, "theta": 0.0}}))
            reloaded = wait_for(lambda s: s["mapping"]["adopted"] and s["mapping"]["source_epoch"] != old_source
                and s["mapping"]["captured_ns"] > load_request_ns,
                                30, "saved graph reload and new publisher epoch")
            report["reload"] = {"old_source": old_source, "new_source": reloaded["mapping"]["source_epoch"],
                                "map": map_metrics(store.load(reloaded["mapping"]["sha256"]), reloaded["mapping"]["odom_in_map"])}
            if not all(report["reload"]["map"]["wall_matches"]):
                raise RuntimeError("reloaded map lost the independently specified walls")
            second = request(endpoint, "start", {"mission": "basic_route"})
            if not second["ok"]:
                raise RuntimeError(second)
            wait_for(lambda s: s["task"]["step"] == "goto_a" and oracle.recent_speed_mps() is not None
                and oracle.recent_speed_mps() > .15, 30, "motion before mapping interruption")
            owned.stop_process(sidecar)
            if sidecar.returncode != 0:
                raise RuntimeError("mapping sidecar did not shut down cleanly")
            wait_for(lambda s: not s["mapping"]["adopted"], 2, "mapping sidecar loss")
            cancel_ns = time.monotonic_ns()
            cancelled = request(endpoint, "cancel")
            if not cancelled["ok"]:
                raise RuntimeError(cancelled)
            stable_since = None
            until = time.monotonic() + 8
            while time.monotonic() < until:
                isolated, _ = status()
                speed = oracle.recent_speed_mps()
                now = time.monotonic()
                stable_since = (stable_since or now) if speed is not None and speed <= .10 else None
                if isolated["task"]["status"] == "CANCELLED" and stable_since is not None and now-stable_since >= 2:
                    if isolated["system_send"] or isolated["action_send"]:
                        raise RuntimeError("cancel retained send authorization")
                    report["mapping_loss_cancel_stop_s"] = (time.monotonic_ns()-cancel_ns)/1e9
                    break
                if isolated["task"]["status"] == "FAILED":
                    raise RuntimeError(isolated["task"]["error"])
                time.sleep(.1)
            else:
                raise TimeoutError("mapping-loss cancellation did not physically stop within the original eight seconds")
            recovery = request(endpoint, "start", {"mission": "safe_recovery"})
            if not recovery["ok"]:
                raise RuntimeError(recovery)
            isolated = wait_for(lambda s: s["task"]["status"] in ("SUCCEEDED", "FAILED"), 25, "explicit recovery")
            if isolated["task"]["status"] != "SUCCEEDED" or isolated["vehicle"]["armed"]:
                raise RuntimeError("explicit recovery did not confirm disarm")
            report["mapping_loss_isolated"] = True
        response = request(endpoint, "shutdown")
        if not response["ok"] or app.wait(timeout=10) or endpoint.exists():
            raise RuntimeError("application cleanup failed")
        owned.stop_process(app)
        report["passed"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            owned.close()
        except Exception as exc:
            report["cleanup_error"] = str(exc)
            report["passed"] = False
        evidence.close()
        (directory / "summary.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-send", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="read-only mapping startup, without a Mission")
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    if not args.smoke and not args.allow_send:
        parser.error("the physical Mission requires --allow-send")
    install_signal_cleanup()
    directory = args.run_dir or ROOT / "artifacts/simulation" / f"ros2-mapping-{uuid4().hex[:8]}"
    report = run(directory.resolve(), smoke=args.smoke)
    print(json.dumps({"directory": str(directory), **report}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
