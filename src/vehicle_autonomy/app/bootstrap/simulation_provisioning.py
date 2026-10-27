"""Fresh owned SITL receive authentication; public protocol setup, no motion.

Shared with the audited simulation harness. Only a fresh session may provision;
ordinary Action receivers never create or reset signing state.
"""
import hashlib
import json
import math
import os
import secrets
import socket
import time
from vehicle_autonomy.vehicles.ardupilot.mavlink.simulation_setup import FreshSimulationSigning


class SimulationProvisioning:
    system_id = 1
    def provision_receive_signing(self, suffix):
        """Public non-actuator protocol setup, ONLY our fresh loopback SITL.

        No EEPROM inspection or control commands. Never record SETUP_SIGNING
        frames, keys, or its parsed secret_key payload in logs/manifests.
        """
        self.signing_key = secrets.token_bytes(32)
        seed = int((time.time() - 1420070400) * 100000)
        protocol = FreshSimulationSigning(self.system_id,self.signing_key,seed)
        self.receive_signing = protocol.auth
        self._setup_protocol = protocol
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
                for reply in protocol.feed(data):
                    connection.sendall(reply)
                if protocol.complete:
                    break
            else:
                raise TimeoutError('BLOCKED: actual signed HEARTBEAT and read-only ACK missing')
        protocol.crosscheck()
        seen = protocol.frames
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
            receiver='MAC first, pinned vehicle/component/link, retained 48-bit watermark'))
        if not suffix:
            from vehicle_autonomy.app.bootstrap.action_ownership import initialize_receive_floor
            initialize_receive_floor(self.run_dir,self.signing_key,self.receive_signing.watermark)
        self._save()

    def verify_parameters(self, expected, label):
        protocol = self._setup_protocol
        observed = {}
        with socket.create_connection(('127.0.0.1',self.port),timeout=1) as connection:
            for request in protocol.parameter_requests(expected):
                connection.sendall(request)
            end=time.monotonic()+15
            while time.monotonic()<end and observed.keys()!=expected.keys():
                self.assert_alive()
                try: data=connection.recv(8192)
                except socket.timeout: continue
                if not data: raise ConnectionError('parameter readback connection closed')
                for name,value in protocol.parameter_values(data).items():
                    if name in expected:
                        if not math.isfinite(value) or abs(value-expected[name])>1e-6:
                            raise RuntimeError('owned simulation parameter readback mismatch: '+name)
                        observed[name]=value
        if observed.keys()!=expected.keys(): raise TimeoutError('owned simulation parameter readback incomplete')
        self.manifest[label] = observed
        # Provisioning floor must include all verified traffic, including reads.
        self.signing_config_path.write_text(json.dumps(dict(key=self.signing_key.hex(),floor=self.receive_signing.watermark)))
        self._save()
