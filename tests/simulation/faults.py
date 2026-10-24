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
        self.hold_tx_commands = set()
        self._held_tx = []
        self._release_tx = []
        self.error = None
        self.records = []
        self._log = log_path.open("w")
        self._lock = Lock()
        self._stop = Event()
        self._connections = []
        self._replays = []
        self._epoch = 0
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def record(self, value):
        with self._lock:
            value = {"host_ns": time.monotonic_ns(), **value}
            self.records.append(value)
            self._log.write(json.dumps(value) + "\n")
            self._log.flush()

    def inject(self, **changes):
        allowed = {'drop_rx', 'drop_ack_command', 'delay_pose_s', 'delay_ack_s',
                   'duplicate_rx', 'repeat_pose', 'drop_tx', 'hold_tx_commands'}
        unknown = changes.keys() - allowed
        if unknown:
            # Validate the entire batch before applying or recording any change.
            raise ValueError('unknown fault injection parameters: ' + ', '.join(sorted(unknown)))
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

    @staticmethod
    def frame_metadata(raw):
        decoded = mav.MAVLink(None).parse_buffer(raw)
        if not decoded or len(decoded) != 1:
            raise ValueError("one complete MAVLink frame required")
        message = decoded[0]
        return {"raw_hex": raw.hex(), "payload": message.to_dict(), "sequence": message.get_seq(),
                "system": message.get_srcSystem(), "component": message.get_srcComponent(),
                "type": message.get_type(), "wire_bytes": len(raw)}

    def replay_rx(self, raw):
        """Replay exact captured bytes on the current connection, never re-pack."""
        metadata = self.frame_metadata(raw)
        with self._lock:
            if not self._connections:
                raise RuntimeError("active owned proxy connection required")
            self._replays.append((self._epoch, raw))
        self.record({"direction": "replay_scheduled", **metadata})

    def release_tx(self):
        """Release only frames previously written by the authorized real writer."""
        with self._lock:
            self._release_tx.extend(self._held_tx)
            self._held_tx = []

    def _run(self):
        while not self._stop.is_set():
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            upstream = None
            pending = []
            try:
                upstream = socket.create_connection(("127.0.0.1", self.upstream_port), timeout=2)
                client.settimeout(.2)
                upstream.settimeout(.2)
                with self._lock:
                    self._connections = [client, upstream]
                    self._epoch += 1
                    epoch = self._epoch
                parsers = {client: mav.MAVLink(None), upstream: mav.MAVLink(None)}
                pending = []
                repeated = {}
                def forward(raw, *, cause, original_hex=None):
                    client.sendall(raw)
                    self.record({"direction": "rx_forward", "cause": cause,
                                 "received_raw_hex": original_hex, "epoch": epoch,
                                 **self.frame_metadata(raw)})
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
                                held = kind == "COMMAND_LONG" and int(message.command) in self.hold_tx_commands
                                record = {"direction": "tx", "type": kind, "forwarded": not self.drop_tx and not held,
                                          "held": held, "epoch": epoch}
                                for field in ("command", "coordinate_frame", "vx", "vy", "vz", "yaw_rate"):
                                    if hasattr(message, field):
                                        record[field] = getattr(message, field)
                                record.update(self.frame_metadata(raw))
                                self.record({**record, "direction": "tx_attempt", "forwarded": False})
                                if held:
                                    with self._lock:
                                        self._held_tx.append((epoch, raw))
                                    self.record(record)
                                elif not self.drop_tx:
                                    try:
                                        upstream.sendall(raw)
                                    except OSError:
                                        self.record({**record, "direction": "tx_uncertain", "forwarded": False})
                                        raise
                                    self.record(record)
                                else:
                                    self.record(record)
                                    self.record({"direction": "tx_discard", "cause": "drop_tx", **self.frame_metadata(raw)})
                            else:
                                dropped = "*" in self.drop_rx or kind in self.drop_rx or (
                                    kind == "COMMAND_ACK" and int(message.command) == self.drop_ack_command)
                                delay = self.delay_pose_s if kind in ("LOCAL_POSITION_NED", "GLOBAL_POSITION_INT", "ATTITUDE") else 0
                                if kind == "COMMAND_ACK":
                                    delay = self.delay_ack_s
                                received_raw = raw
                                if self.repeat_pose and kind in ("ATTITUDE", "GLOBAL_POSITION_INT", "LOCAL_POSITION_NED"):
                                    raw = repeated.setdefault(kind, raw)
                                elif not self.repeat_pose:
                                    repeated.clear()
                                substituted = raw != received_raw
                                cause = "repeat_pose" if substituted else "live"
                                self.record({"direction": "rx", "dropped": dropped or substituted,
                                             "filter_dropped": dropped, "delay_s": delay,
                                             "epoch": epoch, **self.frame_metadata(received_raw)})
                                if dropped or substituted:
                                    self.record({"direction": "rx_discard",
                                                 "cause": "filter" if dropped else "repeat_pose_substitution",
                                                 "epoch": epoch, **self.frame_metadata(received_raw)})
                                if dropped:
                                    continue
                                elif delay:
                                    pending.append((time.monotonic() + delay, raw, cause, received_raw.hex()))
                                else:
                                    forward(raw, cause=cause, original_hex=received_raw.hex())
                                    if kind in self.duplicate_rx:
                                        forward(raw, cause="duplicate_rx", original_hex=received_raw.hex())
                                        self.record({"direction": "duplicate_rx", **self.frame_metadata(raw)})
                    with self._lock:
                        replays, self._replays = self._replays, []
                    with self._lock:
                        released, self._release_tx = self._release_tx, []
                    for scheduled_epoch, raw in released:
                        if scheduled_epoch == epoch:
                            upstream.sendall(raw)
                            self.record({"direction": "tx_release", "epoch": epoch, **self.frame_metadata(raw)})
                        else:
                            self.record({"direction": "tx_discard", "cause": "old_connection", **self.frame_metadata(raw)})
                    for scheduled_epoch, raw in replays:
                        if scheduled_epoch == epoch:
                            forward(raw, cause="explicit_replay")
                        else:
                            self.record({"direction": "rx_discard", "cause": "old_connection_replay",
                                         **self.frame_metadata(raw)})
                    now = time.monotonic()
                    due = [item for item in pending if item[0] <= now]
                    pending = [item for item in pending if item[0] > now]
                    for _, raw, cause, original_hex in due:
                        forward(raw, cause="delayed_" + cause, original_hex=original_hex)
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
                # Preserve evidence of discarded delayed frames; no new-epoch delivery.
                for _, raw, cause, original_hex in pending:
                    self.record({"direction": "rx_discard", "cause": "connection_closed_" + cause,
                                 "received_raw_hex": original_hex, **self.frame_metadata(raw)})
                with self._lock:
                    lost = [item for item in self._held_tx + self._release_tx if item[0] == self._epoch]
                    self._held_tx = [item for item in self._held_tx if item[0] != self._epoch]
                    self._release_tx = [item for item in self._release_tx if item[0] != self._epoch]
                with self._lock:
                    unforwarded = [item for item in self._replays if item[0] == self._epoch]
                    self._replays = [item for item in self._replays if item[0] != self._epoch]
                for _, raw in unforwarded:
                    self.record({"direction": "rx_discard", "cause": "connection_closed_replay", **self.frame_metadata(raw)})
                for _, raw in lost:
                    self.record({"direction": "tx_discard", "cause": "connection_closed", **self.frame_metadata(raw)})
                self.record({"direction": "connection_closed"})

    def close(self):
        self._stop.set()
        self.disconnect()
        self.listener.close()
        self._thread.join(timeout=3)
        if self._thread.is_alive():
            raise RuntimeError("owned TCP proxy did not stop")
        self._log.close()
