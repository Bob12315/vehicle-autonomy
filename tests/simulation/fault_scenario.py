"""Dual-vehicle physical fault acceptance via an owned transparent TCP proxy."""

from dataclasses import replace
import argparse
import json
import math
import os
from pathlib import Path
import signal
import sys
import time
from uuid import uuid4

from contracts.core.geometry import Twist3, Vector3
from contracts.effects.vehicle import ArmEffect, DisarmEffect, LandEffect, ModeEffect, TakeoffEffect, TwistTargetEffect
from deployment.simulation_runtime import SimulationRuntime
from tests.simulation.faults import TcpFaultProxy
from tests.simulation.launch import OwnedSimulation, ROOT, install_signal_cleanup
from tests.simulation.oracle import GazeboTruthOracle
from vehicles.multirotor.ardupilot_commands import ArduPilotCommandTranslator
from vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator


def run(run_dir: Path, kind: str) -> dict:
    run_dir.mkdir(parents=True, exist_ok=False)
    owned = OwnedSimulation(run_dir, kind)
    runtime = proxy = oracle = None
    events = (run_dir / "runtime.jsonl").open("w")
    trajectory = (run_dir / "trajectory.jsonl").open("w")
    summary = {"passed": False, "kind": kind, "run_dir": str(run_dir), "faults": {}}
    limits = json.loads((ROOT / "simulation/scenarios/acceptance-v1.json").read_text())[kind]
    try:
        owned.start()
        oracle = GazeboTruthOracle(owned.world, owned.model)
        proxy = TcpFaultProxy(owned.port, run_dir / "proxy.jsonl")
        profile = replace(owned.profile, port=proxy.port)

        def new_runtime():
            translator = (ArduRoverCommandTranslator if kind == "rover" else ArduPilotCommandTranslator)(mode_ids=profile.mode_ids)
            selected = SimulationRuntime(profile, translator=translator,
                event_sink=lambda event: (events.write(json.dumps(event) + "\n"), events.flush()))
            selected.connect()
            return selected

        runtime = new_runtime()

        def cycle(*, allow_fault=False):
            started = time.monotonic()
            owned.assert_alive()
            if proxy.error:
                raise RuntimeError(proxy.error)
            result = runtime.cycle()
            if result.fault and not allow_fault:
                raise RuntimeError(result.fault)
            state = runtime.world_snapshot().vehicle
            truth = oracle.latest()
            if truth is not None:
                trajectory.write(json.dumps({"host_ns": time.monotonic_ns(), "sim_ns": truth.simulation_ns,
                    "truth": [truth.x_m, truth.y_m, truth.z_m, truth.yaw_rad],
                    "fault": result.fault, "armed": None if state is None else state.operation.armed,
                    "state_velocity": None if state is None or state.reported_twist is None else
                        [state.reported_twist.value.linear.x, state.reported_twist.value.linear.y]}) + "\n")
            time.sleep(max(0, profile.period_ns / 1e9 - (time.monotonic() - started)))
            return state, truth, result

        def warm(timeout=45, *, full=False):
            deadline = time.monotonic() + timeout
            ready = False
            while time.monotonic() < deadline:
                state, truth, result = cycle()
                ready = (state is not None and state.reported_pose is not None
                    and state.reported_twist is not None and runtime.session_id is not None
                    and truth is not None and time.monotonic_ns() - truth.host_received_ns < 500_000_000)
                if ready and not full:
                    return state, truth
            if not ready:
                raise TimeoutError("fresh state/truth after connection unavailable")
            return state, truth

        state, origin = warm(full=True)

        def command(name, effect, *, expected=("COMPLETED",), timeout=8):
            admission = runtime.submit_effect(effect, effect_id=name)
            if admission.reason:
                raise RuntimeError(f"{name} admission failed: {admission.reason}")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                cycle()
                status = runtime.effect_status(name)
                if status["phase"] in (*expected, "REJECTED", "UNKNOWN"):
                    if status["phase"] not in expected:
                        raise RuntimeError(f"{name}: {status}")
                    return status
            raise TimeoutError(f"{name}: {runtime.effect_status(name)}")

        runtime.begin_run()
        before = len(proxy.tx())
        denied = runtime.submit_effect(ModeEffect("GUIDED"), effect_id="unauthorized")
        cycle()
        if denied.reason != "system_send_disabled" or len(proxy.tx()) != before:
            raise AssertionError("default authorization failed to block TX")
        summary["faults"]["unauthorized"] = {"passed": True, "reason": denied.reason, "tx": 0}
        runtime.end_run()
        runtime.begin_run(allow_send=True)
        first = runtime.submit_effect(ModeEffect("GUIDED"), effect_id="duplicate")
        second = runtime.submit_effect(ModeEffect("GUIDED"), effect_id="duplicate")
        if first != second:
            raise AssertionError("duplicate Effect not idempotent")
        try:
            runtime.submit_effect(ArmEffect(), effect_id="duplicate")
        except ValueError:
            pass
        else:
            raise AssertionError("conflicting duplicate accepted")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            cycle()
            if runtime.effect_status("duplicate")["phase"] == "COMPLETED":
                break
        else:
            raise TimeoutError("duplicate mode did not complete")
        if len(proxy.tx()) - before != 1:
            raise AssertionError("duplicate wrote more than once")
        summary["faults"]["duplicate"] = {"passed": True, "tx": 1}
        command("arm", ArmEffect())
        if kind == "copter":
            command("takeoff", TakeoffEffect(1.5), expected=("ACKNOWLEDGED",))
            deadline = time.monotonic() + limits["takeoff_timeout_s"]
            while time.monotonic() < deadline:
                state, truth, _ = cycle()
                if (truth is not None and state is not None and state.reported_pose is not None
                        and abs(truth.z_m - origin.z_m - 1.5) <= limits["takeoff_max_error_m"]
                        and abs(state.reported_twist.value.linear.z) < .2):
                    break
            else:
                raise TimeoutError("fault scenario takeoff target unmet")

        motion_index = 0

        def moving(name):
            nonlocal motion_index
            motion_index += 1
            speed = .3 if motion_index % 2 else -.3
            start = oracle.latest()
            deadline = time.monotonic() + 3
            refresh = 0.0
            count = 0
            while time.monotonic() < deadline:
                if time.monotonic() >= refresh:
                    count += 1
                    result = runtime.submit_effect(TwistTargetEffect("base_link",
                        Twist3(Vector3(speed, 0, 0), Vector3(0, 0, 0)), name), effect_id=f"{name}-{count}")
                    if result.reason:
                        raise RuntimeError(f"{name} motion rejected: {result.reason}")
                    refresh = time.monotonic() + .3
                cycle()
            truth = oracle.latest()
            displacement = math.hypot(truth.x_m - start.x_m, truth.y_m - start.y_m)
            if displacement < .1:
                raise AssertionError(f"{name} had no physical motion: {displacement}")
            if abs(truth.x_m - origin.x_m) > 4.5 or abs(truth.y_m - origin.y_m) > 4.5:
                raise AssertionError("fault scenario exceeded physical fence")
            return {"displacement_m": displacement, "last_effect": f"{name}-{count}"}

        def truth_stop(*, connected=True, timeout=8):
            deadline = time.monotonic() + timeout
            stable = None
            while time.monotonic() < deadline:
                if connected:
                    cycle()
                else:
                    time.sleep(.1)
                truth = oracle.latest()
                speed = oracle.recent_speed_mps()
                yaw_rate = oracle.recent_yaw_rate_rad_s()
                within = (truth is not None and time.monotonic_ns() - truth.host_received_ns < 500_000_000
                    and speed is not None and speed <= limits["stop_max_horizontal_speed_mps"]
                    and yaw_rate is not None and abs(yaw_rate) < .12)
                stable = (stable or time.monotonic()) if within else None
                if stable is not None and time.monotonic() - stable >= limits["stop_stable_s"]:
                    return {"speed_mps": speed, "yaw_rate_rad_s": yaw_rate}
            raise TimeoutError(f"physical Stop failed: {speed}, {yaw_rate}")

        evidence = moving("deadman")
        deadline = time.monotonic() + limits["stop_timeout_s"]
        while time.monotonic() < deadline:
            cycle()
            if runtime._execution.stop_status("deadman").state.value == "CONFIRMED":
                break
        else:
            raise TimeoutError("deadman zero not state-confirmed")
        packets = [packet for packet in proxy.tx() if packet["type"] == "SET_POSITION_TARGET_LOCAL_NED"]
        zero = packets[-1]
        last_motion = next(packet for packet in reversed(packets) if abs(packet.get("vx", 0)) > 0)
        delay = (zero["host_ns"] - last_motion["host_ns"]) / 1e9
        if abs(zero.get("vx", 1)) > 1e-9 or not .8 <= delay <= 1.3:
            raise AssertionError(f"deadman TX deadline wrong: {delay}")
        summary["faults"]["deadman"] = {"passed": True, **evidence, "zero_after_s": delay, **truth_stop()}

        evidence = moving("cancel")
        stops = runtime.end_run()
        if stops != {"cancel": "CONFIRMED"}:
            raise AssertionError(f"Cancel outcome: {stops}")
        if runtime.authority.system_send or runtime.authority.action_send:
            raise AssertionError("Cancel retained SEND")
        summary["faults"]["cancel"] = {"passed": True, **evidence, "stops": stops, **truth_stop()}
        runtime.begin_run(allow_send=True)

        evidence = moving("shutdown")
        stops = runtime.shutdown()
        if stops != {"shutdown": "CONFIRMED"}:
            raise AssertionError(f"shutdown outcome: {stops}")
        summary["faults"]["shutdown_during_motion"] = {"passed": True, **evidence, "stops": stops,
                                                        **truth_stop(connected=False)}

        # Restart an actual Runtime process, and deliver an actual SIGTERM
        # while its typed velocity stream is moving the Gazebo vehicle.
        worker_report = run_dir / "runtime-process-motion.json"
        worker_args = [sys.executable, "-m", "tests.simulation.runtime_worker", "--kind", kind,
                       "--port", str(proxy.port), "--report", str(worker_report), "--allow-send"]
        worker = owned.start_process("runtime_motion", worker_args)
        start = oracle.latest()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            owned.assert_alive()
            truth = oracle.latest()
            if worker_report.exists() and json.loads(worker_report.read_text()).get("ready") and truth:
                distance = math.hypot(truth.x_m - start.x_m, truth.y_m - start.y_m)
                if distance >= .3:
                    break
            time.sleep(.1)
        else:
            raise TimeoutError("Runtime process did not physically move")
        os.kill(worker.pid, signal.SIGTERM)
        worker.wait(timeout=10)
        owned.stop_process(worker)
        report = json.loads(worker_report.read_text())
        if worker.returncode != 0 or not report["passed"] or not report.get("signal_received"):
            raise AssertionError(f"SIGTERM worker failed: {report.get('error')}")
        stopped = truth_stop(connected=False)
        readonly_report = run_dir / "runtime-process-restart.json"
        count = len(proxy.tx())
        readonly = owned.start_process("runtime_readonly", worker_args[:-2] + [str(readonly_report)])
        readonly.wait(timeout=20)
        owned.stop_process(readonly)
        restarted = json.loads(readonly_report.read_text())
        if (readonly.returncode != 0 or not restarted["passed"] or restarted["initial_send"]
                or restarted["initial_lease"] is not None or len(proxy.tx()) != count):
            raise AssertionError("restarted Runtime process retained authority or sent commands")
        summary["faults"]["signal_shutdown"] = {"passed": True, "signal": "SIGTERM", "stops": report["stops"], **stopped}
        summary["faults"]["runtime_process_restart"] = {"passed": True, "new_pid": readonly.pid,
            "old_pid": worker.pid, "send": False, "lease": None, "new_tx": 0}
        runtime = new_runtime()
        warm(timeout=15)
        if runtime.authority.system_send or runtime.authority.lease is not None:
            raise AssertionError("restarted Runtime did not default read-only")
        summary["faults"]["runtime_restart"] = {"passed": True, "send": False, "lease": None}
        runtime.begin_run(allow_send=True)

        def cut_and_recover(label, *, drop=None, delay=0.0, queued=False):
            nonlocal runtime
            evidence = {} if queued else moving(label)
            old_session = runtime.session_id
            if queued:
                # Hold the sole writer behind an unacknowledged mode request.
                # A socket cut can leave already buffered RX readable for one
                # cycle; that must not turn this queued fixture into a TX race.
                proxy.inject(drop_ack_command=176)
                fenced = runtime.submit_effect(ModeEffect("GUIDED"), effect_id=label + "-fence")
                if fenced.reason:
                    raise AssertionError("replay fence not admitted")
                cycle()
                queued_result = runtime.submit_effect(ModeEffect("GUIDED"), effect_id=label + "-queued")
                if queued_result.reason:
                    raise AssertionError("old replay fixture not admitted")
            injection_ns = time.monotonic_ns()
            if drop is not None or delay:
                proxy.inject(drop_rx=drop or set(), delay_pose_s=delay)
            else:
                proxy.disconnect()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                _, _, result = cycle(allow_fault=True)
                if result.fault:
                    break
            else:
                raise TimeoutError(f"{label} did not fault")
            if runtime.authority.system_send or runtime.authority.action_send or runtime.authority.lease is not None:
                raise AssertionError(f"{label} authorization survived")
            stops = runtime.end_run()
            if stops and any(outcome != "UNCONFIRMED" for outcome in stops.values()):
                raise AssertionError(f"{label} incorrectly confirmed lost-link Stop")
            count = len(proxy.tx())
            time.sleep(.15)
            if len(proxy.tx()) != count:
                raise AssertionError(f"{label} TX continued after fault")
            if queued and runtime.effect_status(label + "-queued")["phase"] != "REJECTED":
                raise AssertionError("old queued command not rejected")
            proxy.inject(drop_rx=set(), delay_pose_s=0, drop_ack_command=None)
            runtime.connect()
            warm(timeout=15)
            if runtime.session_id == old_session:
                raise AssertionError("reconnect retained old epoch")
            runtime.begin_run()
            denied = runtime.submit_effect(TwistTargetEffect("base_link",
                Twist3(Vector3(.3, 0, 0), Vector3(0, 0, 0)), label + "-new"), effect_id=label + "-new")
            cycle()
            if denied.reason != "system_send_disabled" or len(proxy.tx()) != count:
                raise AssertionError("reconnect wrote before new authorization")
            summary["faults"][label] = {"passed": True, **evidence, "fault": result.fault,
                "old_session": old_session, "new_session": runtime.session_id, "stops": stops,
                "physical_outcome_at_loss": "UNCONFIRMED", "new_tx_without_authorization": 0,
                "injected_at_ns": injection_ns}
            runtime.end_run()
            runtime.begin_run(allow_send=True)

        cut_and_recover("state_timeout", drop={"LOCAL_POSITION_NED", "GLOBAL_POSITION_INT", "ATTITUDE"})
        cut_and_recover("temporary_disconnect")
        cut_and_recover("long_disconnect", drop={"*"})
        cut_and_recover("delayed_telemetry", delay=3.5)
        cut_and_recover("old_replay", queued=True)
        summary["faults"]["reconnect"] = {"passed": True, "covered_by": ["temporary_disconnect", "old_replay"]}
        summary["faults"]["interrupted_velocity"] = {"passed": True, "covered_by": "temporary_disconnect"}
        summary["faults"]["telemetry_stale"] = {"passed": True, "covered_by": "long_disconnect"}

        if kind == "copter":
            command("land-before-restart", LandEffect(), expected=("ACKNOWLEDGED",))
            deadline = time.monotonic() + limits["land_timeout_s"]
            while time.monotonic() < deadline:
                state, truth, _ = cycle()
                if state and not state.operation.armed and truth and truth.z_m <= origin.z_m + .2:
                    break
            else:
                raise TimeoutError("pre-restart landing not confirmed")
        else:
            command("disarm-before-restart", DisarmEffect())

        proxy.inject(drop_ack_command=176)
        command("ack-timeout", ModeEffect("GUIDED"), expected=("UNKNOWN",))
        if runtime.effect_status("ack-timeout")["reason"] != "ack_timeout_outcome_unknown":
            raise AssertionError("missing ACK not kept unknown")
        summary["faults"]["ack_timeout"] = {"passed": True, **runtime.effect_status("ack-timeout")}
        queued = runtime.submit_effect(ModeEffect("GUIDED"), effect_id="pre-sitl-restart")
        if queued.reason:
            raise AssertionError("restart queued fixture rejected prematurely")
        old_session = runtime.session_id
        owned.stop_process(owned.sitl)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, _, result = cycle(allow_fault=True)
            if result.fault:
                break
        else:
            raise TimeoutError("SITL restart not detected")
        if runtime.effect_status("pre-sitl-restart")["phase"] != "REJECTED":
            raise AssertionError("pre-restart queue not isolated")
        proxy.inject(drop_ack_command=None)
        owned.start_sitl("_restart")
        runtime.connect()
        warm(full=True)
        count = len(proxy.tx())
        runtime.begin_run()
        cycle()
        if len(proxy.tx()) != count or runtime.session_id == old_session or runtime.authority.lease is not None:
            raise AssertionError("SITL restart replayed or restored authorization")
        runtime.end_run()
        runtime.begin_run(allow_send=True)
        command("mode-after-restart", ModeEffect("GUIDED"))
        command("arm-after-restart", ArmEffect())
        command("disarm-after-restart", DisarmEffect())
        summary["faults"]["sitl_restart"] = {"passed": True, "old_session": old_session,
            "new_session": runtime.session_id, "old_queue_tx": 0, "new_explicit_run_completed": True}
        summary["passed"] = True
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if runtime is not None:
            try:
                runtime.shutdown()
            except Exception as exc:
                summary["shutdown_error"] = f"{type(exc).__name__}: {exc}"
        if proxy is not None:
            try:
                proxy.close()
            except Exception as exc:
                summary["proxy_error"] = f"{type(exc).__name__}: {exc}"
        try:
            owned.close()
        except Exception as exc:
            summary["cleanup_error"] = f"{type(exc).__name__}: {exc}"
        events.close()
        trajectory.close()
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("copter", "rover"), required=True)
    parser.add_argument("--allow-send", action="store_true")
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    if not args.allow_send:
        parser.error("explicit --allow-send required")
    install_signal_cleanup()
    summary = run(args.run_dir or ROOT / "artifacts/simulation" / f"fault-{args.kind}-{uuid4().hex[:8]}", args.kind)
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["passed"] and not any(key.endswith("_error") for key in summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
