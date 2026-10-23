"""Transparent localhost TCP fault proxy; no command construction or truth writes."""

import json
from pathlib import Path
import select
import socket
from threading import Event, Lock, Thread
import time

from pymavlink.dialects.v20 import ardupilotmega as mav


class TcpFaultProxy:
    def __init__(self, upstream_port: int, log_path: Path, *, capture_payload=False):
        self.upstream_port = upstream_port
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(2)
        self.listener.settimeout(.1)
        self.port = self.listener.getsockname()[1]
        self.drop_rx = set()
        self.drop_ack_command = None
        self.delay_pose_s = 0.0
        self.delay_ack_s = 0.0
        self.duplicate_rx = set()
        self.repeat_pose = False
        self.capture_payload = capture_payload
        self.drop_tx = False
        self.error = None
        self.records = []
        self._log = log_path.open("w")
        self._lock = Lock()
        self._stop = Event()
        self._connections = []
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def record(self, value):
        with self._lock:
            value = {"host_ns": time.monotonic_ns(), **value}
            self.records.append(value)
            self._log.write(json.dumps(value) + "\n")
            self._log.flush()

    def inject(self, **changes):
        for key, value in changes.items():
            setattr(self, key, value)
        self.record({"direction": "injection", "changes": {k: sorted(v) if isinstance(v, set) else v for k, v in changes.items()}})

    def disconnect(self):
        self.record({"direction": "injection", "disconnect": True})
        with self._lock:
            for connection in self._connections:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def tx(self):
        with self._lock:
            return [dict(record) for record in self.records if record.get("direction") == "tx" and record.get("forwarded")]

    def _run(self):
        while not self._stop.is_set():
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            upstream = None
            try:
                upstream = socket.create_connection(("127.0.0.1", self.upstream_port), timeout=2)
                client.settimeout(.2)
                upstream.settimeout(.2)
                with self._lock:
                    self._connections = [client, upstream]
                parsers = {client: mav.MAVLink(None), upstream: mav.MAVLink(None)}
                pending = []
                repeated = {}
                while not self._stop.is_set():
                    readable, _, _ = select.select([client, upstream], [], [], .02)
                    for source in readable:
                        chunk = source.recv(65536)
                        if not chunk:
                            raise ConnectionError("proxy peer disconnected")
                        for byte in chunk:
                            try:
                                message = parsers[source].parse_char(bytes((byte,)))
                            except mav.MAVError:
                                continue
                            if message is None or message.get_type() == "BAD_DATA":
                                continue
                            kind = message.get_type()
                            raw = bytes(message.get_msgbuf())
                            if source is client:
                                record = {"direction": "tx", "type": kind, "forwarded": not self.drop_tx}
                                for field in ("command", "coordinate_frame", "vx", "vy", "vz", "yaw_rate"):
                                    if hasattr(message, field):
                                        record[field] = getattr(message, field)
                                record["wire_bytes"] = len(raw)
                                self.record(record)
                                if not self.drop_tx:
                                    upstream.sendall(raw)
                            else:
                                dropped = "*" in self.drop_rx or kind in self.drop_rx or (
                                    kind == "COMMAND_ACK" and int(message.command) == self.drop_ack_command)
                                delay = self.delay_pose_s if kind in ("LOCAL_POSITION_NED", "GLOBAL_POSITION_INT", "ATTITUDE") else 0
                                if kind == "COMMAND_ACK":
                                    delay = self.delay_ack_s
                                if self.repeat_pose and kind in ("ATTITUDE", "GLOBAL_POSITION_INT", "LOCAL_POSITION_NED"):
                                    raw = repeated.setdefault(kind, raw)
                                elif not self.repeat_pose:
                                    repeated.clear()
                                record = {"direction": "rx", "type": kind, "dropped": dropped, "delay_s": delay}
                                if self.capture_payload:
                                    record.update(payload=message.to_dict(), raw_hex=raw.hex(),
                                                  system=message.get_srcSystem(), component=message.get_srcComponent(),
                                                  sequence=message.get_seq())
                                self.record(record)
                                if not dropped:
                                    if delay:
                                        pending.append((time.monotonic() + delay, raw))
                                    else:
                                        client.sendall(raw)
                                        if kind in self.duplicate_rx:
                                            client.sendall(raw)
                                            self.record({"direction": "duplicate_rx", "type": kind})
                    now = time.monotonic()
                    due = [item for item in pending if item[0] <= now]
                    pending = [item for item in pending if item[0] > now]
                    for _, raw in due:
                        client.sendall(raw)
            except (OSError, ConnectionError):
                pass
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
            finally:
                with self._lock:
                    self._connections = []
                client.close()
                if upstream is not None:
                    upstream.close()
                # Delayed frames are scoped to this connection and discarded here.
                self.record({"direction": "connection_closed"})

    def close(self):
        self._stop.set()
        self.disconnect()
        self.listener.close()
        self._thread.join(timeout=3)
        if self._thread.is_alive():
            raise RuntimeError("owned TCP proxy did not stop")
        self._log.close()
