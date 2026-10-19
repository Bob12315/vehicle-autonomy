"""Owned localhost Gazebo/SITL launch, isolated ports and evidence manifest."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

from runtime.simulation_profile import SimulationProfile


ROOT = Path(__file__).resolve().parents[2]
ARDUPILOT = Path("/home/level6/ardupilot")
PLUGIN = Path("/home/level6/gz_ws/src/ardupilot_gazebo")


def available(port: int, sock_type=socket.SOCK_STREAM) -> bool:
    with socket.socket(socket.AF_INET, sock_type) as sock:
        if sock_type == socket.SOCK_STREAM:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def choose_instance() -> int:
    for instance in range(1, 100):
        offset = 10 * instance
        if (all(available(port + offset) for port in (5760, 5762, 5763))
                and all(available(port + offset, socket.SOCK_DGRAM) for port in (9002, 5501))):
            return instance
    raise RuntimeError("no free isolated SITL port set")


def output(command: list[str], cwd: Path = ROOT) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=10)
    if result.returncode:
        raise RuntimeError(f"metadata command failed: {command[0]}")
    return result.stdout.strip()


class OwnedSimulation:
    def __init__(self, run_dir: Path, kind: str, *, rover_model='target_rover'):
        if rover_model not in ('target_rover','compact_rover'):raise ValueError('unregistered owned Rover fixture')
        self.run_dir = run_dir
        self.kind = kind
        self.instance = choose_instance()
        self.port = 5760 + 10 * self.instance
        self.json_port = 9002 + 10 * self.instance
        self.world = f"{kind}_{uuid4().hex[:12]}"
        os.environ["GZ_IP"] = "127.0.0.1"
        os.environ["GZ_PARTITION"] = "vaf_" + self.world
        self.model = "iris_with_gimbal" if kind == "copter" else rover_model
        profile_key='compact_rover' if kind=='rover' and rover_model=='compact_rover' else kind
        self.profile = replace(SimulationProfile.load(ROOT / f"simulation/profiles/{profile_key}.toml"), port=self.port)
        self.processes = []
        code_hash=hashlib.sha256()
        for package in ('contracts','core','deployment','runtime','application','applications','actions','app','environments','localization','world_model','mapping','planning','guidance','integrations','sensors','perception','vehicles','protocols','infrastructure','simulation','scripts','tests/simulation'):
            for source in sorted((ROOT/package).rglob('*')):
                if source.is_file() and source.suffix in ('.py','.toml','.json','.sdf','.yaml','.sh','.parm','.cpp','.h'):
                    code_hash.update(str(source.relative_to(ROOT)).encode()+b'\0'+source.read_bytes()+b'\0')
        self.manifest = {"root_source_sha256":code_hash.hexdigest(),
            "working_tree_dirty":bool(output(["git","status","--porcelain"])),"kind": kind, "framework_sha": output(["git", "rev-parse", "HEAD"]),
            "ardupilot_sha": output(["git", "rev-parse", "HEAD"], ARDUPILOT),
            "plugin_sha": output(["git", "rev-parse", "HEAD"], PLUGIN),
            "gazebo_version": output(["gz", "sim", "--version"]),
            "world": self.world, "model": self.model, "instance": self.instance,
            "ports": {"tcp": self.port, "json_udp": self.json_port},
            "gazebo_transport": {"ip": "127.0.0.1", "partition": os.environ["GZ_PARTITION"]},
            "started_at": datetime.now(timezone.utc).isoformat(), "processes": []}
        source_model = (PLUGIN / "models/iris_with_gimbal/model.sdf" if kind == "copter"
                        else ROOT / f"simulation/models/{rover_model}/model.sdf")
        model = ET.parse(source_model)
        for plugin in model.findall(".//plugin"):
            if plugin.attrib.get("name") == "ArduPilotPlugin":
                plugin.find("fdm_port_in").text = str(self.json_port)
        self.model_path = run_dir / "model.sdf"
        model.write(self.model_path)
        source_world = PLUGIN / "worlds/iris_runway.sdf" if kind == "copter" else ROOT / "simulation/worlds/rover_runway.sdf"
        world = ET.parse(source_world)
        world.find("world").set("name", self.world)
        for uri in world.findall(".//include/uri"):
            if uri.text == f"model://{self.model}" or (kind=='rover' and uri.text=='model://target_rover'):
                uri.text = str(self.model_path)
                if kind=='rover':
                    name=world.find('.//include/name')
                    if name is not None:name.text=self.model
        self.world_path = run_dir / "world.sdf"
        world.write(self.world_path)
        self.manifest["source_model"] = str(source_model)
        self.manifest["source_world"] = str(source_world)
        default_names = ("copter.parm", "gazebo-iris.parm") if kind == "copter" else ("rover.parm", "rover-skid.parm")
        self.params = [ARDUPILOT / "Tools/autotest/default_params" / name for name in default_names]
        self.params.append(ROOT / f"simulation/params/{kind}_telemetry.parm")
        self.manifest["parameters"] = [str(p) for p in self.params]
        self.manifest["parameter_files_sha256"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.params}
        self._save()

    def _save(self):
        (self.run_dir / "manifest.json").write_text(json.dumps(self.manifest, indent=2))

    def start_process(self, name, command, *, cwd=None):
        logfile = self.run_dir / f"{name}.log"
        handle = logfile.open("w")
        env = dict(os.environ)
        env["GZ_SIM_RESOURCE_PATH"] = ":".join([str(ROOT / "simulation/models"),
            str(PLUGIN / "models"), str(PLUGIN / "worlds"), env.get("GZ_SIM_RESOURCE_PATH", "")])
        env["GZ_SIM_SYSTEM_PLUGIN_PATH"] = env.get("VAF_SIMULATION_PLUGIN_DIR", str(PLUGIN / "build")) + ":" + env.get("GZ_SIM_SYSTEM_PLUGIN_PATH", "")
        process = subprocess.Popen(command, cwd=cwd or ROOT, env=env, stdout=handle,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        record = {"name": name, "command": command, "pid": process.pid, "pgid": process.pid,
                  "log": str(logfile), "exit_code": None}
        record["start_ticks"] = Path(f"/proc/{process.pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        self.processes.append((process, handle, record))
        self.manifest["processes"].append(record)
        self._save()
        return process

    def start(self):
        self.start_process("gazebo", ["gz", "sim", "-s", "-r", "-v3", str(self.world_path)])
        self.start_sitl()

    def start_sitl(self, suffix=""):
        state_dir = self.run_dir / ("sitl_state" + suffix)
        state_dir.mkdir()
        binary = Path(os.environ.get("VAF_SIMULATION_SITL_BIN_DIR", str(ARDUPILOT / "build/sitl/bin"))) / ("arducopter" if self.kind == "copter" else "ardurover")
        # Direct binary launch avoids sim_vehicle's instance-zero kill_tasks().
        self.sitl = self.start_process("sitl" + suffix, [str(binary), "--model", "JSON", "--speedup", "1",
            "--defaults", ",".join(map(str, self.params)), "--sim-address=127.0.0.1",
            "--home=-35.363262,149.165237,584,90", f"-I{self.instance}"], cwd=state_dir)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            self.assert_alive()
            if not available(self.port):
                return
            time.sleep(.1)
        raise TimeoutError("owned SITL TCP listener unavailable")

    def assert_alive(self):
        for process, _, record in self.processes:
            if record.get("stopped"):
                continue
            if process.poll() is not None:
                raise RuntimeError(f"owned {record['name']} exited {process.returncode}")
            if Path(record["log"]).stat().st_size > 25 * 1024 * 1024:
                raise RuntimeError(f"owned {record['name']} log exceeds 25 MiB")

    def stop_process(self, process):
        entry = next(entry for entry in self.processes if entry[0] is process)
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        entry[2]["stopped"] = True
        entry[2]["exit_code"] = process.returncode
        entry[1].close()
        self._save()

    def close(self):
        for process, _, record in reversed(self.processes):
            if not record.get("stopped"):
                self.stop_process(process)
        self.manifest["ended_at"] = datetime.now(timezone.utc).isoformat()
        remaining = []
        for process, _, record in self.processes:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                continue
            remaining.append(record["pgid"])
        self.manifest["remaining_process_groups"] = remaining
        self.manifest["ports_released"] = all(available(p) for p in (self.port, self.port + 2, self.port + 3)) and available(self.json_port, socket.SOCK_DGRAM)
        self._save()
        if not self.manifest["ports_released"] or remaining:
            raise RuntimeError("owned simulation processes or ports not released")


def install_signal_cleanup():
    def interrupted(signum, frame):
        raise InterruptedError(f"scenario signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
