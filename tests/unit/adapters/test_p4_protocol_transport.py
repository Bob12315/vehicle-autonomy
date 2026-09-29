from __future__ import annotations

import ast
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from pymavlink import mavutil

from contracts.platform.vehicle_commands import Arm, BodyVelocity, SetServo, StopMotion
from infrastructure.transports import (
    ByteTransport, SerialTransport, TcpTransport, TransportKind, TransportSpec, UdpTransport,
)
from protocols.mavlink.ack import decode_command_ack
from protocols.mavlink.codec import send_command_long, send_message_interval_request, send_set_servo
from protocols.mavlink.commands import ack_command_id
from protocols.mavlink.messages import decode_landed_state, message_type
from telemetry_link.config import EndpointConfig, resolve_vehicle_link
from telemetry_link.link_manager import LinkManager
from telemetry_link.models import ActionCommand, ActionType, ControlCommand, ControlType
from tools.telemetry_debug import diagnostic_config, dispatch_diagnostic_command
from vehicles.multirotor.adapter.mavlink import translate_multirotor_mavlink_command


ROOT = Path(__file__).resolve().parents[3]


class MemoryTransport:
    def __init__(self) -> None:
        self.is_open = False
        self.inbound = bytearray()
        self.outbound = bytearray()

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def read(self, max_bytes: int) -> bytes:
        if not self.is_open:
            raise RuntimeError("transport_closed")
        result = bytes(self.inbound[:max_bytes])
        del self.inbound[:max_bytes]
        return result

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise RuntimeError("transport_closed")
        self.outbound.extend(data)
        return len(data)

    def health(self):
        return SimpleNamespace(is_open=self.is_open, last_error=None)


def test_byte_transport_contract_reopen_and_failure() -> None:
    link = MemoryTransport()
    assert isinstance(link, ByteTransport)
    with pytest.raises(RuntimeError, match="transport_closed"):
        link.write(b"x")
    link.open()
    link.inbound.extend(b"abc")
    assert link.read(2) == b"ab"
    assert link.write(b"xy") == 2
    link.close()
    with pytest.raises(RuntimeError, match="transport_closed"):
        link.read(1)
    link.open()
    assert link.read(3) == b"c"
    assert bytes(link.outbound) == b"xy"


def _endpoint(name: str, kind: str, **overrides) -> EndpointConfig:
    fields = dict(name=name, connection_type=kind, serial_port="/dev/ttyUSB0",
                  baudrate=921600, udp_mode="udpin", udp_host="0.0.0.0", udp_port=14550,
                  tcp_host="127.0.0.1", tcp_port=5760, eth_mode="udpout",
                  eth_host="192.0.2.5", eth_port=14551)
    fields.update(overrides)
    return EndpointConfig(**fields)


@pytest.mark.parametrize("source,kind,expected", [
    ("real", "serial", "/dev/ttyUSB0"),
    ("real", "udp", "udpin:0.0.0.0:14550"),
    ("sitl", "tcp", "tcp:127.0.0.1:5760"),
    ("real", "eth", "udpout:192.0.2.5:14551"),
])
def test_legacy_config_resolves_independent_source_protocol_transport(source, kind, expected) -> None:
    profile = resolve_vehicle_link(_endpoint(source, kind))
    assert profile.source == source
    assert profile.protocol == "mavlink"
    assert profile.transport.endpoint == expected
    assert profile.transport.kind in {TransportKind.SERIAL, TransportKind.UDP, TransportKind.TCP}


def test_transport_spec_rejects_invalid_endpoint() -> None:
    with pytest.raises(ValueError, match="UDP mode"):
        TransportSpec(TransportKind.UDP, host="127.0.0.1", port=14550, udp_mode="radio")
    with pytest.raises(ValueError, match="network transport"):
        TransportSpec(TransportKind.TCP, host="127.0.0.1", port=0)


def test_serial_udp_tcp_implement_same_byte_contract_without_opening_hardware() -> None:
    transports = (
        SerialTransport(TransportSpec(TransportKind.SERIAL, device="/dev/ttyUSB0", baudrate=921600)),
        UdpTransport(TransportSpec(TransportKind.UDP, host="127.0.0.1", port=14550,
                                   udp_mode="udpin")),
        TcpTransport(TransportSpec(TransportKind.TCP, host="127.0.0.1", port=5760)),
    )
    for transport in transports:
        assert isinstance(transport, ByteTransport)
        assert not transport.is_open
        assert not transport.health().is_open
        with pytest.raises(RuntimeError, match="transport_closed"):
            transport.write(b"test")


class RecordingMav:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def command_long_send(self, *args) -> None:
        self.calls.append(args)


def test_protocol_encoding_and_ack_decode() -> None:
    master = SimpleNamespace(target_system=2, target_component=3, mav=RecordingMav())
    send_set_servo(master, 8, 1500)
    assert master.mav.calls[-1] == (2, 3, mavutil.mavlink.MAV_CMD_DO_SET_SERVO,
                                     0, 8.0, 1500.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    assert ack_command_id(SetServo(8, 1500).kind) == mavutil.mavlink.MAV_CMD_DO_SET_SERVO
    send_message_interval_request(master, "ATTITUDE", 20.0)
    assert master.mav.calls[-1][2] == mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL
    assert master.mav.calls[-1][4:6] == (float(mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE), 50000.0)
    with pytest.raises(ValueError, match="seven"):
        send_command_long(master, 1, [0.0])
    message = SimpleNamespace(command=183, result=0, progress=80,
                              target_system=2, target_component=3,
                              get_srcSystem=lambda: 2, get_srcComponent=lambda: 1)
    ack = decode_command_ack(message)
    assert (ack.mav_command, ack.source_system, ack.progress, ack.target_system) == (183, 2, 80, 2)
    landed = decode_landed_state(SimpleNamespace(
        landed_state=mavutil.mavlink.MAV_LANDED_STATE_ON_GROUND))
    assert landed.on_ground and not landed.in_air
    assert message_type(SimpleNamespace(get_type=lambda: "COMMAND_ACK")) == "COMMAND_ACK"


def test_vehicle_adapter_preserves_servo_and_stop_semantics() -> None:
    servo = translate_multirotor_mavlink_command(SetServo(8, 1500))
    assert isinstance(servo, ActionCommand)
    assert servo.action_type is ActionType.SET_SERVO
    assert servo.params == {"channel": 8, "pwm": 1500}
    arm = translate_multirotor_mavlink_command(Arm())
    assert isinstance(arm, ActionCommand) and arm.action_type is ActionType.ARM
    velocity = translate_multirotor_mavlink_command(BodyVelocity(1, 2, 3))
    assert isinstance(velocity, ControlCommand) and velocity.command_type is ControlType.VELOCITY
    stop = translate_multirotor_mavlink_command(StopMotion())
    assert isinstance(stop, ControlCommand) and stop.command_type is ControlType.STOP
    assert (stop.vx, stop.vy, stop.vz, stop.yaw_rate) == (0, 0, 0, 0)


def test_diagnostic_default_refuses_writer_invocation() -> None:
    class Manager:
        def arm(self):
            raise AssertionError("writer reached")

    result = dispatch_diagnostic_command(Manager(), "arm", logging.getLogger(__name__),
                                         allow_send=False)
    assert not result.ok
    assert "read-only" in result.message


def test_diagnostic_cli_preserves_telemetry_args_and_defaults_read_only() -> None:
    cfg, allow_send = diagnostic_config(["--data-source", "sitl"])
    assert not allow_send and cfg.diagnostic_read_only
    assert not cfg.request_message_intervals and not cfg.attitude_udp_enabled
    assert cfg.data_source == "sitl"
    enabled, allow_send = diagnostic_config(["--allow-send", "--data-source", "real"])
    assert allow_send and not enabled.diagnostic_read_only
    assert enabled.data_source == "real"


def test_read_only_source_session_does_not_construct_writer(monkeypatch) -> None:
    import telemetry_link.link_manager as link_manager_module

    cfg, _ = diagnostic_config(["--data-source", "sitl"])
    manager = LinkManager(cfg)
    runtime = manager.runtimes["sitl"]

    class Client:
        target_system = 1
        target_component = 0
        autopilot_component = 1
        connection_string = "fake"
        is_sitl = True

        def connect(self): pass
        def wait_heartbeat(self, timeout): pass
        def bootstrap_vehicle_state(self): return None
        def close(self): pass

    class Receiver:
        def __init__(self, *args):
            self.started = False

        def start(self):
            self.started = True

    runtime.client = Client()
    monkeypatch.setattr(link_manager_module, "TelemetryReceiver", Receiver)
    runtime._connect_and_start_workers(logging.getLogger(__name__))
    assert runtime.receiver is not None and runtime.receiver.started
    assert runtime.sender is None
    assert runtime.command_broker is None
    assert runtime.broker_worker is None


@pytest.mark.parametrize("directory,forbidden", [
    ("contracts/core", {"pymavlink", "telemetry_link", "serial", "socket"}),
    ("application/core", {"pymavlink", "telemetry_link", "serial", "socket"}),
    ("missions/core", {"pymavlink", "telemetry_link", "serial", "socket"}),
    ("contracts/vehicle", {"pymavlink"}),
    ("contracts/platform", {"pymavlink"}),
    ("infrastructure/transports", {"contracts", "missions", "execution", "pymavlink", "telemetry_link"}),
    ("protocols/mavlink", {"missions", "app", "application", "execution",
                           "vehicles", "web", "web_ui", "yolo_app", "cuadc2026"}),
])
def test_import_boundary(directory: str, forbidden: set[str]) -> None:
    violations = []
    for path in (ROOT / directory).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = (item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                modules = (node.module or "",)
            else:
                continue
            violations.extend(f"{path.relative_to(ROOT)}: {module}" for module in modules
                              if module.split(".", 1)[0] in forbidden)
    assert not violations, "\n".join(violations)
