"""Owned Rover SITL/Gazebo protocol and physical acceptance scenario."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time
from uuid import uuid4

from contracts.core.geometry import Pose3, Quaternion, Twist3, Vector3
from contracts.effects.vehicle import ArmEffect, DisarmEffect, ModeEffect, PoseTargetEffect, StopMotionEffect, TwistTargetEffect
from deployment.simulation_runtime import SimulationRuntime
from tests.simulation.oracle import GazeboTruthOracle
from tests.simulation.launch import OwnedSimulation, ROOT, install_signal_cleanup
from vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator


def run(run_dir: Path, *, gazebo: bool = False, full: bool = False) -> dict:
    run_dir.mkdir(parents=True, exist_ok=False)
    owned = OwnedSimulation(run_dir, "rover")
    runtime = None
    trajectory = (run_dir / "trajectory.jsonl").open("w")
    events = (run_dir / "runtime.jsonl").open("w")
    summary = {"passed": False, "run_dir": str(run_dir), "steps": {}}
    try:
        owned.start()
        oracle = GazeboTruthOracle(owned.world, owned.model)
        profile = owned.profile
        runtime = SimulationRuntime(profile, translator=ArduRoverCommandTranslator(mode_ids=profile.mode_ids),
            event_sink=lambda event: (events.write(json.dumps(event) + "\n"), events.flush()))
        runtime.connect()
        warmup_deadline = time.monotonic() + profile.warmup_ns / 1e9
        message_counts = {}
        status_texts = []
        original_poll = runtime._session.poll

        def counted_poll(now):
            messages = original_poll(now)
            for message in messages:
                name = message.get_type()
                message_counts[name] = message_counts.get(name, 0) + 1
                if name == "STATUSTEXT":
                    status_texts.append(str(message.text))
            return messages

        runtime._session.poll = counted_poll

        def cycle():
            started = time.monotonic()
            owned.assert_alive()
            result = runtime.cycle()
            if result.fault:
                raise RuntimeError(result.fault)
            time.sleep(max(0, profile.period_ns / 1e9 - (time.monotonic() - started)))
            state = runtime.world_snapshot().vehicle
            truth = None if oracle is None else oracle.latest()
            if truth is not None:
                twist = None if state is None else state.reported_twist
                trajectory.write(json.dumps({"host_ns": time.monotonic_ns(),
                    "truth": [truth.x_m, truth.y_m, truth.z_m, truth.yaw_rad],
                    "state_velocity": None if twist is None else
                    [twist.value.linear.x, twist.value.linear.y, twist.value.angular.z]}) + "\n")
            return state

        deadline = time.monotonic() + 35
        received = 0
        while time.monotonic() < deadline:
            state = cycle()
            if state is not None:
                received += 1
            if state and state.reported_pose and state.reported_twist and runtime.session_id:
                break
        else:
            summary["startup_diagnostic"] = {"session": runtime.session_id,
                "state_cycles": received, "quality": None if state is None else state.health.quality.value,
                "mode": None if state is None else state.operation.native_mode,
                "pose": state is not None and state.reported_pose is not None,
                "twist": state is not None and state.reported_twist is not None,
                "message_counts": message_counts}
            raise TimeoutError("fresh Rover pose/twist unavailable")
        summary["initial_state"] = {"mode": state.operation.native_mode,
                                    "armed": state.operation.armed,
                                    "position": list((state.reported_pose.value.position.x,
                                                      state.reported_pose.value.position.y))}
        if oracle is not None:
            truth = oracle.latest()
            if truth is None:
                raise RuntimeError("Gazebo Rover truth unavailable")
            summary["initial_truth"] = [truth.x_m, truth.y_m, truth.z_m]
        summary["status_texts"] = status_texts
        while time.monotonic() < warmup_deadline:
            cycle()
        runtime.begin_run(allow_send=True)

        def command(name, effect, timeout=12):
            result = runtime.submit_effect(effect, effect_id=name)
            if result.reason:
                raise RuntimeError(f"{name} rejected: {result.reason}")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                state = cycle()
                status = runtime.effect_status(name)
                if status["phase"] in ("COMPLETED", "REJECTED", "UNKNOWN"):
                    summary["steps"][name] = {**status, "armed": state.operation.armed,
                                                "mode": state.operation.native_mode}
                    summary["status_texts"] = status_texts
                    return status
            twist = None if state is None or state.reported_twist is None else state.reported_twist.value
            summary["timeout_diagnostic"] = {"state_linear": None if twist is None else
                [twist.linear.x, twist.linear.y, twist.linear.z],
                "state_angular": None if twist is None else
                [twist.angular.x, twist.angular.y, twist.angular.z],
                "truth_speed": None if oracle is None else oracle.recent_speed_mps()}
            raise TimeoutError(f"{name} status timeout: {runtime.effect_status(name)}")

        for name, effect in (("guided", ModeEffect("GUIDED")), ("arm", ArmEffect())):
            if command(name, effect)["phase"] != "COMPLETED":
                raise RuntimeError(f"{name} failed")
        drive = TwistTargetEffect("base_link", Twist3(Vector3(.5, 0, 0), Vector3(0, 0, 0)), "drive")
        result = runtime.submit_effect(drive, effect_id="drive")
        if result.reason:
            raise RuntimeError(f"drive rejected: {result.reason}")
        deadline = time.monotonic() + .3
        while time.monotonic() < deadline:
            cycle()
        summary["steps"]["drive"] = runtime.effect_status("drive")
        if oracle is not None:
            truth = oracle.latest()
            summary["drive_truth"] = None if truth is None else [truth.x_m, truth.y_m, truth.z_m]
        if summary["steps"]["drive"]["phase"] != "TRANSMITTED":
            raise RuntimeError("Rover setpoint was not transmitted")
        stop = command("stop", StopMotionEffect("drive"), timeout=8)
        if stop["phase"] != "COMPLETED":
            raise RuntimeError("Rover Stop unconfirmed")
        if full:
            if oracle is None:
                raise ValueError("full Rover scenario requires Gazebo truth")
            scenario = json.loads((ROOT / "simulation/scenarios/acceptance-v1.json").read_text())["rover"]

            def wrap(angle):
                return (angle + math.pi) % (2 * math.pi) - math.pi

            def stop_and_confirm(name, stream):
                requested = time.monotonic()
                deadline = requested + scenario["stop_timeout_s"]
                status = command(name + "-stop", StopMotionEffect(stream),
                                 timeout=scenario["stop_timeout_s"])
                if status["phase"] != "COMPLETED":
                    raise RuntimeError(f"{name} Stop not telemetry confirmed")
                stable_since = None
                speed = yaw_rate = None
                while time.monotonic() < deadline:
                    state = cycle()
                    truth = oracle.latest()
                    speed = oracle.recent_speed_mps()
                    yaw_rate = oracle.recent_yaw_rate_rad_s()
                    within = (truth is not None and time.monotonic_ns() - truth.host_received_ns < 500_000_000
                              and state is not None and state.reported_twist is not None
                              and speed is not None and yaw_rate is not None
                              and speed <= scenario["stop_max_horizontal_speed_mps"]
                              and abs(yaw_rate) <= .12)
                    stable_since = (stable_since or time.monotonic()) if within else None
                    if (stable_since is not None and time.monotonic() - stable_since >= scenario["stop_stable_s"]
                            and time.monotonic() <= deadline):
                        summary["steps"][name + "-stop-truth"] = {"speed_mps": speed,
                            "yaw_rate_rad_s": yaw_rate, "elapsed_from_request_s": time.monotonic() - requested}
                        return
                raise TimeoutError(f"{name} Gazebo Stop not stable: speed={speed}, yaw_rate={yaw_rate}")

            def drive_segment(name, speed, yaw_rate, duration, *, axis=None, turn_sign=None):
                start = oracle.latest()
                if start is None:
                    raise RuntimeError("missing Rover Gazebo truth")
                twist = Twist3(Vector3(speed, 0, 0), Vector3(0, 0, yaw_rate))
                next_send = 0.0
                deadline = time.monotonic() + duration
                count = 0
                transmitted_ids = set()
                while time.monotonic() < deadline:
                    if time.monotonic() >= next_send:
                        count += 1
                        effect_id = f"{name}-{count}"
                        result = runtime.submit_effect(TwistTargetEffect("base_link", twist, name),
                                                       effect_id=effect_id)
                        if result.reason:
                            raise RuntimeError(f"{name} rejected: {result.reason}")
                        next_send = time.monotonic() + .3
                    cycle()
                    if runtime.effect_status(f"{name}-{count}")["phase"] == "TRANSMITTED":
                        transmitted_ids.add(f"{name}-{count}")
                    current = oracle.latest()
                    if current is not None and current.host_received_ns > start.host_received_ns:
                        delta_x, delta_y = current.x_m - start.x_m, current.y_m - start.y_m
                        projection = delta_x * math.cos(start.yaw_rad) + delta_y * math.sin(start.yaw_rad)
                        rotation = wrap(current.yaw_rad - start.yaw_rad)
                        if (axis is not None and projection * axis >= scenario["minimum_translation_m"]
                                or turn_sign is not None and rotation * turn_sign >= math.radians(scenario["minimum_turn_deg"])):
                            break
                finish = oracle.latest()
                if (finish is None or finish.host_received_ns <= start.host_received_ns
                        or time.monotonic_ns() - finish.host_received_ns >= 500_000_000):
                    raise RuntimeError(f"{name} has no fresh Gazebo motion sample")
                dx, dy = finish.x_m - start.x_m, finish.y_m - start.y_m
                heading_projection = dx * math.cos(start.yaw_rad) + dy * math.sin(start.yaw_rad)
                yaw_change = wrap(finish.yaw_rad - start.yaw_rad)
                summary["steps"][name] = {"setpoints": count, "transmitted_setpoints": len(transmitted_ids),
                    "truth_delta_xy": [dx, dy], "heading_projection_m": heading_projection,
                    "truth_delta_yaw_rad": yaw_change}
                if len(transmitted_ids) < 2:
                    raise RuntimeError(f"{name} lacked transmitted setpoints")
                if axis is not None and heading_projection * axis < scenario["minimum_translation_m"]:
                    raise RuntimeError(f"{name} failed signed translation threshold")
                if turn_sign is not None and yaw_change * turn_sign < math.radians(scenario["minimum_turn_deg"]):
                    raise RuntimeError(f"{name} failed signed turn threshold")
                stop_and_confirm(name, name)

            drive_segment("forward", .5, 0, scenario["translation_timeout_s"], axis=1)
            drive_segment("reverse", -.5, 0, scenario["translation_timeout_s"], axis=-1)
            drive_segment("left", .35, .5, scenario["turn_timeout_s"], turn_sign=1)
            drive_segment("right", .35, -.5, scenario["turn_timeout_s"], turn_sign=-1)
            drive_segment("pivot-left", 0, .5, scenario["turn_timeout_s"], turn_sign=1)
            drive_segment("pivot-right", 0, -.5, scenario["turn_timeout_s"], turn_sign=-1)

            runtime.end_run()
            runtime.begin_run(allow_send=True)
            state = cycle()
            initial = oracle.latest()
            p = state.reported_pose.value.position
            offset_x, offset_y = scenario["goto_offset_enu_m"]
            target = Pose3(Vector3(p.x + offset_x, p.y + offset_y, 0),
                           Quaternion(0, 0, 0, 1))
            truth_target = (initial.x_m + offset_x, initial.y_m + offset_y)
            count = 0
            transmitted_ids = set()
            next_send = 0.0
            stable_since = None
            deadline = time.monotonic() + scenario["goto_timeout_s"]
            while time.monotonic() < deadline:
                if time.monotonic() >= next_send:
                    count += 1
                    effect_id = f"goto-{count}"
                    result = runtime.submit_effect(PoseTargetEffect("odom", target, "goto"),
                                                   effect_id=effect_id)
                    if result.reason:
                        raise RuntimeError(f"Rover Goto rejected: {result.reason}")
                    next_send = time.monotonic() + .3
                state = cycle()
                truth = oracle.latest()
                if runtime.effect_status(f"goto-{count}")["phase"] == "TRANSMITTED":
                    transmitted_ids.add(f"goto-{count}")
                if (state is None or state.reported_pose is None or truth is None
                        or truth.host_received_ns <= initial.host_received_ns
                        or time.monotonic_ns() - truth.host_received_ns >= 500_000_000):
                    continue
                sp = state.reported_pose.value.position
                state_error = math.hypot(sp.x - target.position.x, sp.y - target.position.y)
                truth_error = math.hypot(truth.x_m - truth_target[0], truth.y_m - truth_target[1])
                summary["steps"]["goto"] = {"setpoints": count,
                    "transmitted_setpoints": len(transmitted_ids),
                    "state_error_m": state_error, "truth_error_m": truth_error,
                    "target_xy": truth_target, "truth_xy": [truth.x_m, truth.y_m]}
                within = (state_error <= scenario["goto_max_horizontal_error_m"]
                          and truth_error <= scenario["goto_max_horizontal_error_m"])
                stable_since = (stable_since or time.monotonic()) if within else None
                if stable_since is not None and time.monotonic() - stable_since >= 1:
                    break
            else:
                raise TimeoutError(f"Rover Goto did not arrive: {summary['steps'].get('goto')}")
            if len(transmitted_ids) < 2:
                raise RuntimeError("Rover Goto lacked transmitted setpoints")
            stop_and_confirm("goto", "goto")
        if command("disarm", DisarmEffect())["phase"] != "COMPLETED":
            raise RuntimeError("Rover Disarm failed")
        if oracle is not None:
            truth = oracle.latest()
            summary["final_truth"] = None if truth is None else [truth.x_m, truth.y_m, truth.z_m]
        summary["passed"] = True
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if runtime is not None:
            try:
                runtime.shutdown()
            except Exception as exc:
                summary["shutdown_error"] = f"{type(exc).__name__}: {exc}"
        try:
            owned.close()
        except Exception as exc:
            summary["cleanup_error"] = f"{type(exc).__name__}: {exc}"
        trajectory.close()
        events.close()
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-send", action="store_true")
    parser.add_argument("--gazebo", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    if not args.allow_send:
        parser.error("explicit --allow-send required")
    install_signal_cleanup()
    summary = run(args.run_dir or ROOT / "artifacts/simulation" / f"rover-protocol-{uuid4().hex[:8]}",
                  gazebo=args.gazebo or args.full, full=args.full)
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["passed"] and "shutdown_error" not in summary and "cleanup_error" not in summary else 1


if __name__ == "__main__":
    raise SystemExit(main())
