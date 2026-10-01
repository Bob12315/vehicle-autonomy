"""Owned internal Rover SITL protocol probe; Gazebo acceptance is Phase 5."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from uuid import uuid4

from contracts.core.geometry import Twist3, Vector3
from contracts.effects.vehicle import ArmEffect, DisarmEffect, ModeEffect, StopMotionEffect, TwistTargetEffect
from deployment.simulation_runtime import SimulationRuntime
from runtime.simulation_profile import SimulationProfile
from tests.simulation.copter_scenario import ARDUPILOT, OwnedProcesses, ROOT, listening
from vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator


def run(run_dir: Path) -> dict:
    run_dir.mkdir(parents=True, exist_ok=False)
    owned = OwnedProcesses(run_dir)
    runtime = None
    summary = {"passed": False, "run_dir": str(run_dir), "steps": {}}
    try:
        if listening():
            raise RuntimeError("SITL TCP port 5760 already occupied")
        owned.start("sitl", ["python", str(ARDUPILOT / "Tools/autotest/sim_vehicle.py"),
             "-v", "Rover", "-f", "rover-skid", "--no-mavproxy", "--no-rebuild",
             "--add-param-file", str(ARDUPILOT / "Tools/autotest/default_params/rover.parm"),
             "--add-param-file", str(ARDUPILOT / "Tools/autotest/default_params/rover-skid.parm"),
             "--add-param-file", str(ROOT / "simulation/params/rover_telemetry.parm"),
             "--use-dir", str(run_dir / "sitl_state")])
        ready_deadline = time.monotonic() + 25
        while time.monotonic() < ready_deadline and not listening():
            time.sleep(.2)
        if not listening():
            raise TimeoutError("Rover SITL listener unavailable")
        profile = SimulationProfile.load(ROOT / "simulation/profiles/rover.toml")
        runtime = SimulationRuntime(profile, translator=ArduRoverCommandTranslator(mode_ids=profile.mode_ids))
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
            result = runtime.cycle()
            if result.fault:
                raise RuntimeError(result.fault)
            time.sleep(max(0, profile.period_ns / 1e9 - (time.monotonic() - started)))
            return runtime.world_snapshot().vehicle

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
        if summary["steps"]["drive"]["phase"] != "TRANSMITTED":
            raise RuntimeError("Rover setpoint was not transmitted")
        stop = command("stop", StopMotionEffect("drive"), timeout=8)
        if stop["phase"] != "COMPLETED":
            raise RuntimeError("Rover Stop unconfirmed")
        if command("disarm", DisarmEffect())["phase"] != "COMPLETED":
            raise RuntimeError("Rover Disarm failed")
        summary["passed"] = True
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if runtime is not None:
            try:
                runtime.shutdown()
            except Exception as exc:
                summary["shutdown_error"] = f"{type(exc).__name__}: {exc}"
        owned.close()
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-send", action="store_true")
    args = parser.parse_args()
    if not args.allow_send:
        parser.error("explicit --allow-send required")
    summary = run(ROOT / "artifacts/simulation" / f"rover-protocol-{uuid4().hex[:8]}")
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["passed"] and "shutdown_error" not in summary else 1


if __name__ == "__main__":
    raise SystemExit(main())
