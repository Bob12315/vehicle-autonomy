"""Owned localhost Gazebo/SITL launch, isolated ports and evidence manifest."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import secrets
from vehicle_autonomy.vehicles.ardupilot.mavlink.signing import ReceiveSigning
import socket
import subprocess
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

from vehicle_autonomy.app.bootstrap.simulation_profile import SimulationProfile
from tests.simulation.credentials import OwnedCredentials


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
    def __init__(self, run_dir: Path, kind: str, *, rover_model='target_rover', rover_actuation='baseline', confirmation_signing=False):
        if rover_model not in ('target_rover','compact_rover'):raise ValueError('unregistered owned Rover fixture')
        if rover_actuation not in ('baseline','low_rate'):raise ValueError('unregistered actuation fixture')
        self.run_dir = run_dir
        self.kind = kind
        self.confirmation_signing = confirmation_signing
        self.instance = choose_instance()
        self.port = 5760 + 10 * self.instance
        self.json_port = 9002 + 10 * self.instance
        self.world = f"{kind}_{uuid4().hex[:12]}"
        os.environ["GZ_IP"] = "127.0.0.1"
        os.environ["GZ_PARTITION"] = "vaf_" + self.world
        if kind not in ("rover", "copter", "plane"):
            raise ValueError("unregistered simulation kind")
        self.model = "iris_with_gimbal" if kind == "copter" else "plane_runway" if kind == "plane" else rover_model
        profile_key='compact_rover' if kind=='rover' and rover_model=='compact_rover' else kind
        self.profile = replace(SimulationProfile.load(ROOT / f"simulation/profiles/{profile_key}.toml"), port=self.port)
        self.processes = []
        code_hash=hashlib.sha256()
        for package in ('src/vehicle_autonomy','configs','simulation','scripts','tests/simulation'):
            for source in sorted((ROOT/package).rglob('*')):
                if source.is_file() and source.suffix in ('.py','.toml','.json','.sdf','.yaml','.sh','.parm','.cpp','.h','.js','.html','.css'):
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
                        else ROOT / f"simulation/models/{self.model}/model.sdf")
        if kind=='rover' and rover_model=='target_rover' and rover_actuation=='low_rate':
            source_model=ROOT/'simulation/models/target_rover/navigation.sdf'
        self.manifest['actuation_profile']=rover_actuation if kind=='rover' else 'baseline'
        model = ET.parse(source_model)
        for plugin in model.findall(".//plugin"):
            if plugin.attrib.get("name") == "ArduPilotPlugin":
                plugin.find("fdm_port_in").text = str(self.json_port)
        self.model_path = run_dir / "model.sdf"
        model.write(self.model_path)
        source_world = PLUGIN / "worlds/iris_runway.sdf" if kind == "copter" else ROOT / f"simulation/worlds/{'plane' if kind == 'plane' else 'rover'}_runway.sdf"
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
        default_names = ("copter.parm", "gazebo-iris.parm") if kind == "copter" else ("gazebo-zephyr.parm",) if kind == "plane" else ("rover.parm", "rover-skid.parm")
        self.params = [ARDUPILOT / "Tools/autotest/default_params" / name for name in default_names]
        self.params.append(ROOT / f"simulation/params/{kind}_telemetry.parm")
        self.manifest["parameters"] = [str(p) for p in self.params]
        self.manifest["parameter_files_sha256"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.params}
        self.credentials = OwnedCredentials(run_dir, self.manifest)
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
                  "log": str(logfile), "cwd": str(Path(cwd or ROOT).absolute()), "exit_code": None}
        record["start_ticks"] = Path(f"/proc/{process.pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        self.processes.append((process, handle, record))
        self.manifest["processes"].append(record)
        self._save()
        return process

    def start(self):
        self.start_process("gazebo", ["gz", "sim", "-s", "-r", "-v3", str(self.world_path)])
        self.start_sitl()

    def start_sitl(self, suffix=""):
        state_dir = self.credentials.create_state(suffix)
        self._save()  # parent can clean up even if this scenario is killed
        binary = Path(os.environ.get("VAF_SIMULATION_SITL_BIN_DIR", str(ARDUPILOT / "build/sitl/bin"))) / ({"copter": "arducopter", "rover": "ardurover", "plane": "arduplane"}[self.kind])
        plugin_library = Path(os.environ.get("VAF_SIMULATION_PLUGIN_DIR", str(PLUGIN / "build"))) / "libArduPilotPlugin.so"
        self.manifest["binary_path"] = str(binary)
        self.manifest["binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
        self.manifest["plugin_library"] = str(plugin_library)
        self.manifest["plugin_library_sha256"] = hashlib.sha256(plugin_library.read_bytes()).hexdigest()
        # Direct binary launch avoids sim_vehicle's instance-zero kill_tasks().
        self.sitl = self.start_process("sitl" + suffix, [str(binary), "--model", "JSON", "--speedup", "1",
            "--defaults", ",".join(map(str, self.params)), "--sim-address=127.0.0.1",
            "--home=-35.363262,149.165237,584,90", f"-I{self.instance}"], cwd=state_dir)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            self.assert_alive()
            if not available(self.port):
                if self.confirmation_signing:
                    self.provision_receive_signing(suffix)
                    if self.kind == "plane":
                        self.verify_plane_parameters()
                return
            time.sleep(.1)
        raise TimeoutError("owned SITL TCP listener unavailable")

    def provision_receive_signing(self, suffix):
        """Public non-actuator protocol setup, ONLY our fresh loopback SITL.

        No EEPROM inspection or control commands. Never record SETUP_SIGNING
        frames, keys, or its parsed secret_key payload in logs/manifests.
        """
        from pymavlink.dialects.v20 import ardupilotmega as mav
        self.signing_key = secrets.token_bytes(32)
        seed = int((time.time() - 1420070400) * 100000)
        self.receive_signing = ReceiveSigning(self.signing_key, initial_timestamp=seed)
        peer = mav.MAVLink(None, srcSystem=250, srcComponent=191)
        parser = mav.MAVLink(None)
        parser.robust_parsing = True  # channel 0 may contain startup console text
        seen = []; setup = requested = False
        with socket.create_connection(('127.0.0.1', self.port), timeout=1) as connection:
            end = time.monotonic() + 25
            while time.monotonic() < end:
                self.assert_alive()
                try:
                    data = connection.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    raise ConnectionError('owned signing setup connection closed')
                for message in parser.parse_buffer(data) or []:
                    if message.get_type() == 'BAD_DATA':
                        continue
                    if (message.get_srcSystem(),message.get_srcComponent()) != (1,1):
                        continue
                    if not setup:
                        if message.get_type() != 'HEARTBEAT':
                            continue
                        if message.base_mode & 128:
                            raise RuntimeError('signing provisioning requires unarmed owned SITL')
                        connection.sendall(peer.setup_signing_encode(1,1,self.signing_key,seed).pack(peer))
                        peer.seq = (peer.seq+1)&255
                        setup = True
                        continue
                    stamp = self.receive_signing.verify(message,system=1,component=1)
                    if stamp is None:
                        continue
                    if message.get_type() in ('HEARTBEAT','COMMAND_ACK'):
                        seen.append(dict(type=message.get_type(), timestamp=stamp,
                            raw_hex=bytes(message.get_msgbuf()).hex(), payload=message.to_dict()))
                    if message.get_type() == 'HEARTBEAT' and not requested:
                        # Request HEARTBEAT, a read-only protocol query, to
                        # verify downlink ACK signing without a vehicle effect.
                        connection.sendall(peer.command_long_encode(1,1,512,0,0,0,0,0,0,0,0).pack(peer))
                        requested = True
                if any(x['type']=='HEARTBEAT' for x in seen) and any(x['type']=='COMMAND_ACK' and x['payload']['command']==512 for x in seen):
                    break
            else:
                raise TimeoutError('BLOCKED: actual signed HEARTBEAT and read-only ACK missing')
        # Separate, standard pymavlink verifier cross-check of actual wire bytes.
        independent = mav.MAVLink(None)
        independent.signing.secret_key = self.signing_key
        independent.signing.timestamp = seed
        for item in seen:
            decoded = independent.parse_buffer(bytes.fromhex(item['raw_hex']))
            if not decoded or not decoded[0].get_signed():
                raise AssertionError('independent pymavlink signature verification failed')
        self.signing_config_path = self.run_dir / ('receive-signing'+suffix+'.private')
        with os.fdopen(os.open(self.signing_config_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as private:
            self.credentials.register_private(self.signing_config_path.name, private.fileno())
            self._save()  # persist ownership BEFORE writing any credential
            json.dump(dict(key=self.signing_key.hex(),floor=self.receive_signing.watermark),private)
        proof = dict(method='public SETUP_SIGNING + read-only MAV_CMD_REQUEST_MESSAGE',
                     independent_pymavlink_verified=True, initial_timestamp=seed, frames=seen)
        (self.run_dir / ('signing-support'+suffix+'.json')).write_text(json.dumps(proof,indent=2))
        self.manifest.setdefault('signing_epochs',[]).append(dict(initial_timestamp=seed,
            key_sha256=hashlib.sha256(self.signing_key).hexdigest(),proof='signing-support'+suffix+'.json',
            receiver='MAC first, pinned (1,1,0), retained 48-bit watermark'))
        self._save()

    def verify_plane_parameters(self):
        """Read-only public parameter echo; no EEPROM or key inspection."""
        from pymavlink.dialects.v20 import ardupilotmega as mav
        expected = {"RTL_ALTITUDE": 50., "TKOFF_ALT": 50., "AUTOLAND_WP_ALT": 40.,
                    "AUTOLAND_WP_DIST": 400., "SERVO3_MIN": 1100., "SERVO3_MAX": 1900.,
                    "FENCE_ENABLE": 1., "FENCE_TYPE": 3., "FENCE_ACTION": 1.,
                    "FENCE_RADIUS": 2000., "FENCE_ALT_MAX": 150., "FENCE_ALT_MAX_TP": 1.}
        peer = mav.MAVLink(None, srcSystem=250, srcComponent=191)
        parser = mav.MAVLink(None); parser.robust_parsing = True
        observed = {}
        with socket.create_connection(('127.0.0.1',self.port),timeout=1) as connection:
            for name in expected:
                connection.sendall(peer.param_request_read_encode(1,1,name.encode(),-1).pack(peer))
                peer.seq=(peer.seq+1)&255
            end=time.monotonic()+15
            while time.monotonic()<end and observed.keys()!=expected.keys():
                self.assert_alive()
                try: data=connection.recv(8192)
                except socket.timeout: continue
                if not data: raise ConnectionError('parameter readback connection closed')
                for message in parser.parse_buffer(data) or []:
                    if message.get_type()=='BAD_DATA': continue
                    if self.receive_signing.verify(message,system=1,component=1) is None: continue
                    if message.get_type()!='PARAM_VALUE': continue
                    name=str(message.param_id).rstrip('\0')
                    if name in expected:
                        value=float(message.param_value)
                        if abs(value-expected[name])>1e-6:
                            raise RuntimeError('owned Plane parameter readback mismatch: '+name)
                        observed[name]=value
        if observed.keys()!=expected.keys(): raise TimeoutError('owned Plane parameter readback incomplete')
        self.manifest['plane_parameter_readback'] = observed
        # Provisioning floor must include all verified traffic, including reads.
        self.signing_config_path.write_text(json.dumps(dict(key=self.signing_key.hex(),floor=self.receive_signing.watermark)))
        self._save()

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
        errors = []
        for process, _, record in reversed(self.processes):
            if not record.get("stopped"):
                try:
                    self.stop_process(process)
                except Exception as exc:
                    errors.append(type(exc).__name__)
        remaining = []
        for process, _, record in self.processes:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                continue
            remaining.append(record["pgid"])
        self.manifest["remaining_process_groups"] = remaining
        self.manifest["ports_released"] = all(available(p) for p in (self.port, self.port + 2, self.port + 3)) and available(self.json_port, socket.SOCK_DGRAM)
        try:
            if remaining:
                raise RuntimeError("credential writers still alive; refusing concurrent destruction")
            self.credentials.destroy()
            self.manifest['ephemeral_signing_config_removed'] = True
        finally:
            # Drop parent references; Python bytes cannot promise RAM zeroization.
            self.signing_key = self.receive_signing = None
            self.manifest["ended_at"] = datetime.now(timezone.utc).isoformat()
            self._save()
        if not self.manifest["ports_released"] or remaining or errors:
            raise RuntimeError("owned simulation cleanup failed: " + ",".join(errors))


def install_signal_cleanup():
    def interrupted(signum, frame):
        raise InterruptedError(f"scenario signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
