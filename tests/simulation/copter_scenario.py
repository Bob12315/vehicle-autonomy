"""Owned Copter/Gazebo physical scenario using the normal Effect chain."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time
from uuid import uuid4

from contracts.core.geometry import Pose3, Quaternion, Twist3, Vector3
from contracts.effects.vehicle import ArmEffect, LandEffect, ModeEffect, PoseTargetEffect, StopMotionEffect, TakeoffEffect, TwistTargetEffect
from deployment.simulation_runtime import SimulationRuntime
from tests.simulation.oracle import GazeboTruthOracle
from tests.simulation.launch import OwnedSimulation, ROOT, install_signal_cleanup
from vehicles.multirotor.ardupilot_commands import ArduPilotCommandTranslator


def yaw_only(pose: Pose3) -> Pose3:
    q = pose.orientation
    yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
    return Pose3(pose.position, Quaternion(0, 0, math.sin(yaw / 2), math.cos(yaw / 2)))


def run(run_dir: Path, *, goto: bool = False, full: bool = False) -> dict:
    run_dir.mkdir(parents=True, exist_ok=False)
    owned = OwnedSimulation(run_dir, "copter")
    runtime = None
    observations = (run_dir / "observations.jsonl").open("w")
    events = (run_dir / "runtime.jsonl").open("w")
    summary = {"passed": False, "steps": {}, "run_dir": str(run_dir)}
    try:
        owned.start()
        oracle = GazeboTruthOracle(owned.world, owned.model)
        profile = owned.profile
        scenario = json.loads((ROOT / "simulation/scenarios/acceptance-v1.json").read_text())["copter"]
        runtime = SimulationRuntime(profile,
            translator=ArduPilotCommandTranslator(mode_ids=profile.mode_ids),
            event_sink=lambda event: (events.write(json.dumps(event) + "\n"), events.flush()))
        runtime.connect()

        def cycle() -> tuple[object, object]:
            started = time.monotonic()
            owned.assert_alive()
            result = runtime.cycle()
            if result.fault is not None:
                raise RuntimeError(result.fault)
            state = runtime.world_snapshot().vehicle
            truth = oracle.latest()
            if truth is not None:
                observations.write(json.dumps({
                    "host_ns": time.monotonic_ns(), "sim_ns": truth.simulation_ns,
                    "truth": [truth.x_m, truth.y_m, truth.z_m, truth.yaw_rad],
                    "state": None if state is None or state.reported_pose is None else [
                        state.reported_pose.value.position.x, state.reported_pose.value.position.y,
                        state.reported_pose.value.position.z],
                    "armed": None if state is None else state.operation.armed,
                    "mode": None if state is None else state.operation.native_mode,
                }) + "\n")
                observations.flush()
            time.sleep(max(0, profile.period_ns / 1e9 - (time.monotonic() - started)))
            return state, truth

        warmup_end = time.monotonic() + profile.warmup_ns / 1e9
        while time.monotonic() < warmup_end:
            cycle()
        state, truth = cycle()
        if state is None or state.reported_pose is None or truth is None:
            raise RuntimeError("fresh state and Gazebo pose required")
        origin_state_z = state.reported_pose.value.position.z
        origin_truth = truth
        origin_truth_z = truth.z_m
        runtime.begin_run(allow_send=True)

        def command(name: str, effect, *, timeout_s: float = 12) -> dict:
            submitted = runtime.submit_effect(effect, effect_id=name)
            if submitted.reason is not None:
                raise RuntimeError(f"{name} rejected: {submitted.reason}")
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                cycle()
                status = runtime.effect_status(name)
                if status["phase"] in ("COMPLETED", "REJECTED", "UNKNOWN"):
                    summary["steps"][name] = status
                    return status
            raise TimeoutError(f"{name} command status timeout: {runtime.effect_status(name)}")

        for name, effect in (("mode", ModeEffect("GUIDED")), ("arm", ArmEffect())):
            status = command(name, effect)
            if status["phase"] != "COMPLETED":
                raise RuntimeError(f"{name} command failed: {status}")
        start_ns = time.monotonic_ns()
        target_height = scenario["takeoff_height_m"]
        submitted = runtime.submit_effect(TakeoffEffect(target_height), effect_id="takeoff")
        if submitted.reason is not None:
            raise RuntimeError(f"takeoff rejected: {submitted.reason}")
        deadline = time.monotonic() + scenario["takeoff_timeout_s"]
        reached = False
        stable_since = None
        while time.monotonic() < deadline:
            state, truth = cycle()
            status = runtime.effect_status("takeoff")
            if status["phase"] in ("REJECTED", "UNKNOWN"):
                raise RuntimeError(f"takeoff command failed: {status}")
            if (status["phase"] == "ACKNOWLEDGED" and truth is not None
                    and truth.host_received_ns > start_ns and state is not None
                    and state.reported_pose is not None
                    and state.reported_pose.captured_at.monotonic_ns > start_ns):
                state_rise = state.reported_pose.value.position.z - origin_state_z
                truth_rise = truth.z_m - origin_truth_z
                state_vz = None if state.reported_twist is None else state.reported_twist.value.linear.z
                truth_vz = oracle.recent_vertical_speed_mps()
                summary["steps"]["takeoff"] = {"phase": status["phase"],
                    "state_rise_m": state_rise, "truth_rise_m": truth_rise,
                    "state_vertical_mps": state_vz, "truth_vertical_mps": truth_vz}
                steady = (abs(state_rise - target_height) <= scenario["takeoff_max_error_m"]
                          and abs(truth_rise - target_height) <= scenario["takeoff_max_error_m"]
                          and state_vz is not None and truth_vz is not None
                          and abs(state_vz) <= .2 and abs(truth_vz) <= .2)
                stable_since = (stable_since or time.monotonic()) if steady else None
                if stable_since is not None and time.monotonic() - stable_since >= scenario["stop_stable_s"]:
                    reached = True
                    break
        if not reached:
            raise TimeoutError(f"takeoff physical target unmet: {summary['steps'].get('takeoff')}")
        if goto:
            state, truth = cycle()
            hold_pose = yaw_only(state.reported_pose.value)
            hold_truth_xy = (truth.x_m, truth.y_m)
            hold_deadline = time.monotonic() + scenario["stop_stable_s"]
            next_refresh = 0.0
            counter = 0
            while time.monotonic() < hold_deadline:
                if time.monotonic() >= next_refresh:
                    counter += 1
                    admission = runtime.submit_effect(PoseTargetEffect("odom", hold_pose, "hold"),
                                                     effect_id=f"hold-{counter}")
                    if admission.reason is not None:
                        raise RuntimeError(f"Hold setpoint rejected: {admission.reason}")
                    next_refresh = time.monotonic() + .3
                state, truth = cycle()
                if (state is None or state.reported_pose is None or truth is None
                        or abs(state.reported_pose.value.position.z - origin_state_z - target_height) > scenario["takeoff_max_error_m"]
                        or abs(truth.z_m - origin_truth_z - target_height) > scenario["takeoff_max_error_m"]
                        or ((truth.x_m - hold_truth_xy[0])**2 +
                            (truth.y_m - hold_truth_xy[1])**2)**.5 > .5):
                    raise RuntimeError("GUIDED Hold left pose tolerance")
            summary["steps"]["hold"] = {"setpoints": counter, "truth_xy": [truth.x_m, truth.y_m],
                                          "truth_z_m": truth.z_m}
            admission = runtime.submit_effect(StopMotionEffect("hold"), effect_id="hold-stop")
            if admission.reason is not None:
                raise RuntimeError(f"Hold Stop rejected: {admission.reason}")
            deadline = time.monotonic() + scenario["stop_timeout_s"]
            while time.monotonic() < deadline:
                cycle()
                if runtime.effect_status("hold-stop")["phase"] == "COMPLETED":
                    break
            else:
                raise TimeoutError("Hold Stop not confirmed")
            state, truth = cycle()
            goto_started_ns = time.monotonic_ns()
            current = yaw_only(state.reported_pose.value)
            offset_x, offset_y = scenario["goto_offset_enu_m"]
            target = Pose3(Vector3(current.position.x + offset_x, current.position.y + offset_y,
                                   current.position.z), current.orientation)
            truth_target = (truth.x_m + offset_x, truth.y_m + offset_y)
            arrived = False
            deadline = time.monotonic() + scenario["goto_timeout_s"]
            next_refresh = 0.0
            counter = 0
            stable_since = None
            transmitted_ids: set[str] = set()
            while time.monotonic() < deadline:
                if time.monotonic() >= next_refresh:
                    counter += 1
                    admission = runtime.submit_effect(PoseTargetEffect("odom", target, "goto"),
                                                     effect_id=f"goto-{counter}")
                    if admission.reason is not None:
                        raise RuntimeError(f"Goto setpoint rejected: {admission.reason}")
                    next_refresh = time.monotonic() + .3
                state, truth = cycle()
                latest = runtime.effect_status(f"goto-{counter}")
                if latest is not None and latest["phase"] == "TRANSMITTED":
                    transmitted_ids.add(f"goto-{counter}")
                if (state is None or state.reported_pose is None or truth is None
                        or truth.host_received_ns <= goto_started_ns
                        or state.reported_pose.captured_at.monotonic_ns <= goto_started_ns):
                    continue
                p = state.reported_pose.value.position
                state_error = ((p.x - target.position.x)**2 + (p.y - target.position.y)**2)**.5
                truth_error = ((truth.x_m - truth_target[0])**2 +
                               (truth.y_m - truth_target[1])**2)**.5
                summary["steps"]["goto"] = {"setpoints": counter, "transmitted_setpoints": len(transmitted_ids),
                                              "state_error_m": state_error,
                                              "truth_error_m": truth_error,
                                              "truth_xy": [truth.x_m, truth.y_m],
                                              "target_xy": list(truth_target)}
                within = (state_error <= scenario["goto_max_horizontal_error_m"]
                          and truth_error <= scenario["goto_max_horizontal_error_m"])
                stable_since = (stable_since or time.monotonic()) if within else None
                if stable_since is not None and time.monotonic() - stable_since >= 1:
                    arrived = True
                    break
            if not arrived or not transmitted_ids:
                raise TimeoutError(f"Goto did not arrive: {summary['steps'].get('goto')}")
            admission = runtime.submit_effect(StopMotionEffect("goto"), effect_id="goto-stop")
            if admission.reason is not None:
                raise RuntimeError(f"Goto Stop rejected: {admission.reason}")
            stopped_since = None
            deadline = time.monotonic() + scenario["stop_timeout_s"]
            while time.monotonic() < deadline:
                state, truth = cycle()
                status = runtime.effect_status("goto-stop")
                speed = oracle.recent_speed_mps()
                stopped = (status["phase"] == "COMPLETED" and speed is not None
                           and speed <= scenario["stop_max_horizontal_speed_mps"])
                stopped_since = (stopped_since or time.monotonic()) if stopped else None
                if stopped_since is not None and time.monotonic() - stopped_since >= scenario["stop_stable_s"]:
                    summary["steps"]["goto-stop"] = {"status": status, "truth_speed_mps": speed}
                    break
            else:
                raise TimeoutError(f"Goto Stop not confirmed: {runtime.effect_status('goto-stop')}")
            if full:
                def stream(name: str, frame: str, linear: Vector3, yaw_rate: float,
                           duration_s: float) -> tuple[object, object]:
                    start_truth = oracle.latest()
                    started_ns = time.monotonic_ns()
                    next_refresh = 0.0
                    counter = 0
                    transmitted_ids: set[str] = set()
                    until = time.monotonic() + duration_s
                    peak_speed = 0.0
                    peak_yaw_rate = 0.0
                    while time.monotonic() < until:
                        if time.monotonic() >= next_refresh:
                            counter += 1
                            effect = TwistTargetEffect(frame,
                                Twist3(linear, Vector3(0, 0, yaw_rate)), name)
                            result = runtime.submit_effect(effect, effect_id=f"{name}-{counter}")
                            if result.reason is not None:
                                raise RuntimeError(f"{name} rejected: {result.reason}")
                            next_refresh = time.monotonic() + .3
                        state, truth = cycle()
                        latest_id = f"{name}-{counter}"
                        latest_status = runtime.effect_status(latest_id)
                        if latest_status is not None and latest_status["phase"] == "TRANSMITTED":
                            transmitted_ids.add(latest_id)
                        velocity = oracle.recent_velocity_enu()
                        if velocity is not None:
                            peak_speed = max(peak_speed, math.hypot(velocity[0], velocity[1]))
                        observed_yaw_rate = oracle.recent_yaw_rate_rad_s()
                        if observed_yaw_rate is not None:
                            peak_yaw_rate = max(peak_yaw_rate, observed_yaw_rate)
                    summary["steps"][name] = {
                        "setpoints": counter,
                        "transmitted_setpoints": len(transmitted_ids),
                        "truth_delta_xy": [truth.x_m - start_truth.x_m, truth.y_m - start_truth.y_m],
                        "truth_delta_yaw_rad": math.atan2(math.sin(truth.yaw_rad - start_truth.yaw_rad),
                                                          math.cos(truth.yaw_rad - start_truth.yaw_rad)),
                        "peak_horizontal_speed_mps": peak_speed,
                        "peak_positive_yaw_rate_rad_s": peak_yaw_rate,
                    }
                    if not transmitted_ids:
                        raise RuntimeError(f"{name} never reached the MAVLink writer")
                    if (truth.host_received_ns <= started_ns or state is None
                            or state.reported_pose is None
                            or state.reported_pose.captured_at.monotonic_ns <= started_ns):
                        raise RuntimeError(f"{name} lacked post-command truth or VehicleState")
                    return start_truth, truth

                def stop_stream(name: str, *, yaw: bool = False) -> None:
                    result = runtime.submit_effect(StopMotionEffect(name), effect_id=f"{name}-stop")
                    if result.reason is not None:
                        raise RuntimeError(f"{name} Stop rejected: {result.reason}")
                    stable_since = None
                    deadline = time.monotonic() + scenario["stop_timeout_s"]
                    while time.monotonic() < deadline:
                        cycle()
                        phase = runtime.effect_status(f"{name}-stop")["phase"]
                        speed = oracle.recent_speed_mps()
                        yaw_speed = oracle.recent_yaw_rate_rad_s()
                        steady = (phase == "COMPLETED" and speed is not None
                                  and speed <= scenario["stop_max_horizontal_speed_mps"]
                                  and (not yaw or yaw_speed is not None and abs(yaw_speed) <= .15))
                        stable_since = (stable_since or time.monotonic()) if steady else None
                        if stable_since is not None and time.monotonic() - stable_since >= scenario["stop_stable_s"]:
                            summary["steps"][f"{name}-stop"] = {"phase": phase,
                                "truth_speed_mps": speed, "truth_yaw_rate_rad_s": yaw_speed}
                            return
                    raise TimeoutError(f"{name} Stop physical state not confirmed")

                velocity_x = scenario["velocity_enu_mps"][0]
                _, finish = stream("velocity-x", "odom", Vector3(velocity_x, 0, 0), 0,
                                   scenario["velocity_segment_s"])
                if summary["steps"]["velocity-x"]["truth_delta_xy"][0] < scenario["velocity_min_displacement_m"]:
                    raise RuntimeError("positive local X velocity did not move world +X")
                if not scenario["velocity_speed_min_mps"] <= summary["steps"]["velocity-x"]["peak_horizontal_speed_mps"] <= scenario["velocity_speed_max_mps"]:
                    raise RuntimeError("local X speed magnitude outside acceptance band")
                stop_stream("velocity-x")
                _, finish = stream("velocity-y", "odom", Vector3(0, velocity_x, 0), 0,
                                   scenario["velocity_segment_s"])
                if summary["steps"]["velocity-y"]["truth_delta_xy"][1] < scenario["velocity_min_displacement_m"]:
                    raise RuntimeError("positive local Y velocity did not move world +Y")
                if not scenario["velocity_speed_min_mps"] <= summary["steps"]["velocity-y"]["peak_horizontal_speed_mps"] <= scenario["velocity_speed_max_mps"]:
                    raise RuntimeError("local Y speed magnitude outside acceptance band")
                stop_stream("velocity-y")
                _, finish = stream("yaw-positive", "base_link", Vector3(0, 0, 0),
                                   scenario["positive_yaw_rate_rad_s"], scenario["yaw_segment_s"])
                if summary["steps"]["yaw-positive"]["truth_delta_yaw_rad"] < scenario["yaw_min_rotation_rad"]:
                    raise RuntimeError("positive body yaw rate did not rotate world counterclockwise")
                if summary["steps"]["yaw-positive"]["peak_positive_yaw_rate_rad_s"] < .2:
                    raise RuntimeError("positive yaw rate magnitude too small")
                stop_stream("yaw-positive", yaw=True)
                start, finish = stream("body-forward", "base_link", Vector3(velocity_x, 0, 0), 0,
                                       scenario["velocity_segment_s"])
                dx, dy = summary["steps"]["body-forward"]["truth_delta_xy"]
                projection = dx * math.cos(start.yaw_rad) + dy * math.sin(start.yaw_rad)
                summary["steps"]["body-forward"]["heading_projection_m"] = projection
                if projection < scenario["body_forward_min_projection_m"]:
                    raise RuntimeError("forward body command did not follow vehicle heading")
                cancel_requested = time.monotonic()
                deadline = cancel_requested + scenario["stop_timeout_s"]
                stops = runtime.end_run()
                summary["steps"]["cancel"] = {"stops": stops}
                if stops.get("body-forward") != "CONFIRMED":
                    raise RuntimeError(f"Cancel did not confirm Stop: {stops}")
                stable_since = None
                while time.monotonic() < deadline:
                    cycle()
                    speed = oracle.recent_speed_mps()
                    stable_since = (stable_since or time.monotonic()) if speed is not None and speed <= scenario["stop_max_horizontal_speed_mps"] else None
                    if stable_since is not None and time.monotonic() - stable_since >= scenario["stop_stable_s"]:
                        summary["steps"]["cancel"]["elapsed_from_request_s"] = time.monotonic() - cancel_requested
                        break
                else:
                    raise TimeoutError("Cancel did not physically stop")
                runtime.begin_run(allow_send=True)
                rtl_requested = time.monotonic()
                deadline = rtl_requested + scenario["rtl_timeout_s"]
                status = command("rtl", ModeEffect("RTL"))
                if status["phase"] != "COMPLETED":
                    raise RuntimeError(f"RTL mode failed: {status}")
                while time.monotonic() < deadline:
                    state, truth = cycle()
                    if state is None or truth is None:
                        continue
                    distance = math.hypot(truth.x_m - origin_truth.x_m,
                                          truth.y_m - origin_truth.y_m)
                    summary["steps"]["rtl_truth"] = {"home_error_m": distance,
                        "height_m": truth.z_m - origin_truth_z,
                        "armed": state.operation.armed,
                        "elapsed_from_request_s": time.monotonic() - rtl_requested}
                    if (distance <= scenario["rtl_home_error_m"] and truth.z_m <= origin_truth_z + .2
                            and not state.operation.armed):
                        break
                else:
                    raise TimeoutError(f"RTL physical return incomplete: {summary['steps'].get('rtl_truth')}")
        summary["passed"] = True
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if runtime is not None:
            try:
                if runtime.session_id is not None and runtime.authority.system_send:
                    try:
                        current_state = runtime.world_snapshot().vehicle
                        current_truth = oracle.latest()
                        already_landed = (current_state is not None and not current_state.operation.armed
                                          and current_truth is not None and current_truth.z_m <= origin_truth_z + .2)
                        if not already_landed:
                            land_request = runtime.submit_effect(LandEffect(), effect_id="cleanup-land")
                            if land_request.reason is not None:
                                raise RuntimeError(f"Land rejected: {land_request.reason}")
                        deadline = time.monotonic() + scenario["land_timeout_s"]
                        landed = already_landed
                        while time.monotonic() < deadline:
                            if landed:
                                break
                            cycle()
                            state = runtime.world_snapshot().vehicle
                            truth = oracle.latest()
                            if (state is not None and not state.operation.armed and truth is not None
                                    and truth.z_m <= origin_truth_z + .2):
                                landed = True
                                break
                        summary["cleanup_landed"] = landed
                        if not already_landed:
                            summary["cleanup_land_command"] = runtime.effect_status("cleanup-land")
                            if summary["cleanup_land_command"]["phase"] not in ("ACKNOWLEDGED", "COMPLETED"):
                                raise RuntimeError("Land command lacked ACK")
                        if not landed:
                            raise TimeoutError("Land did not reach ground and disarm within configured timeout")
                    except Exception as exc:
                        summary["cleanup_error"] = f"{type(exc).__name__}: {exc}"
                runtime.shutdown()
            except Exception as exc:
                summary["shutdown_error"] = f"{type(exc).__name__}: {exc}"
        try:
            owned.close()
        except Exception as exc:
            summary["cleanup_error"] = f"{type(exc).__name__}: {exc}"
        observations.close()
        events.close()
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-send", action="store_true", help="explicitly authorize local SITL commands")
    parser.add_argument("--goto", action="store_true", help="also verify Hold, local Goto and Stop")
    parser.add_argument("--full", action="store_true", help="also verify velocity, yaw, Cancel and RTL")
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    if not args.allow_send:
        parser.error("--allow-send is required for the takeoff probe")
    install_signal_cleanup()
    run_dir = args.run_dir or ROOT / "artifacts/simulation" / f"copter-scenario-{uuid4().hex[:8]}"
    summary = run(run_dir, goto=args.goto or args.full, full=args.full)
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["passed"] and "cleanup_error" not in summary and "shutdown_error" not in summary else 1


if __name__ == "__main__":
    raise SystemExit(main())
