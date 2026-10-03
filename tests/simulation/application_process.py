"""Owned SITL/Gazebo acceptance through the public application subprocess/CLI."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4
from app.control import request
from tests.simulation.launch import OwnedSimulation, ROOT, install_signal_cleanup
from tests.simulation.oracle import GazeboTruthOracle


def run(run_dir, kind):
    run_dir.mkdir(parents=True, exist_ok=False)
    owned = OwnedSimulation(run_dir, kind)
    summary = {"passed": False, "checks": []}
    endpoint = run_dir / "app.sock"
    evidence = (run_dir / "application-status.jsonl").open("w")
    try:
        owned.start()
        oracle = GazeboTruthOracle(owned.world, owned.model)
        config = run_dir / "profile.toml"
        config.write_text((ROOT / f"simulation/profiles/{kind}.toml").read_text().replace(
            "port = 5760", f"port = {owned.port}"))
        profile_name = f"{kind}_sim"

        def launch(allow_send, suffix):
            return owned.start_process("application" + suffix, [sys.executable, "-m", "app.main", "run",
                "--profile", profile_name, "--config", str(config), "--control-socket", str(endpoint),
                *(["--allow-send"] if allow_send else [])])

        def status():
            response = request(endpoint, "status")
            if not response["ok"]:
                raise RuntimeError(response)
            state = response["result"]
            truth = oracle.latest()
            evidence.write(json.dumps({"host_ns": time.monotonic_ns(), "status": state,
                "truth": None if truth is None else [truth.x_m, truth.y_m, truth.z_m]}) + "\n")
            evidence.flush()
            return state

        def wait(predicate, timeout=20):
            until = time.monotonic() + timeout
            last = None
            while time.monotonic() < until:
                owned.assert_alive()
                if endpoint.exists():
                    last = status()
                    if predicate(last):
                        return last
                time.sleep(.2)
            raise TimeoutError(f"application condition unmet: {last}")

        def cli(operation, *flags):
            result = subprocess.run([sys.executable, "-m", "app.main", "ctl", "--profile", profile_name,
                "--control-socket", str(endpoint), operation, *flags], capture_output=True, text=True, timeout=4)
            response = json.loads(result.stdout)
            if (result.returncode == 0) != response["ok"]:
                raise AssertionError("CLI result mismatch")
            return response

        app = launch(False, "-readonly")
        first = wait(lambda s: s["state"] == "READY", 60)
        oracle.wait_new(after_host_ns=time.monotonic_ns(), timeout_s=3)
        second = wait(lambda s: s["world_version"]["revision"] > first["world_version"]["revision"])
        assert not second["system_send"] and not second["action_send"]
        assert second["localization"] is not None
        assert second["localization"]["position"] == second["vehicle"]["pose"]["position"]
        assert second["localization"]["frame"] == "odom"
        assert second["localization"]["age_ns"] < owned.profile.safety.max_snapshot_age_ns
        assert second["world_age_ns"] < owned.profile.safety.max_snapshot_age_ns
        assert not cli("start", "--mission", "disarmed_mode")["ok"]
        app.terminate()
        assert app.wait(timeout=6) == 0 and not endpoint.exists()
        owned.stop_process(app)
        summary["checks"].append("readonly_freshness_sigterm")

        app = launch(True, "-send")
        wait(lambda s: s["state"] == "READY")
        assert cli("start", "--mission", "disarmed_mode", "--request-id", "start-one")["ok"]
        repeated = cli("start", "--mission", "disarmed_mode", "--request-id", "start-one")
        task_id = repeated["result"]["task_id"]
        finished = wait(lambda s: s["task"] and s["task"]["status"] in ("SUCCEEDED", "FAILED"))
        assert finished["task"]["status"] == "SUCCEEDED", finished
        assert finished["task"]["task_id"] == task_id
        assert all(e["phase"] == "COMPLETED" for e in finished["task"]["effects"].values())
        assert not finished["system_send"] and not finished["action_send"]
        summary["checks"].append("typed_mode_ack_and_observation_idempotence")
        # Cancel immediately from the public request boundary; sent modes remain observable.
        assert cli("start", "--mission", "disarmed_mode")["ok"]
        assert cli("cancel")["ok"]
        cancelled = wait(lambda s: s["task"]["status"] == "CANCELLED")
        assert not cancelled["system_send"]
        summary["checks"].append("cancel_revoke")
        session = cancelled["session_id"]
        owned.stop_process(owned.sitl)
        wait(lambda s: not s["connected"], 12)
        owned.start_sitl("-reconnect")
        reconnected = wait(lambda s: s["state"] == "READY" and s["session_id"] != session, 60)
        assert not reconnected["system_send"] and reconnected["task"]["status"] == "CANCELLED"
        assert reconnected["localization"]["transform_epoch"] != cancelled["localization"]["transform_epoch"]
        assert reconnected["world_version"]["generation"] != cancelled["world_version"]["generation"]
        summary["checks"].append("reconnect_readonly_new_epoch")
        assert cli("shutdown")["ok"]
        assert app.wait(timeout=6) == 0 and not endpoint.exists()
        owned.stop_process(app)
        summary["checks"].append("shutdown_cleanup")
        summary["passed"] = True
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            owned.close()
        except Exception as exc:
            summary["cleanup_error"] = str(exc)
            summary["passed"] = False
        evidence.close()
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("copter", "rover"), required=True)
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    install_signal_cleanup()
    result = run(args.run_dir or ROOT / "artifacts/simulation" / f"application-{args.kind}-{uuid4().hex[:8]}", args.kind)
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
