"""Explicit localhost ArduCopter SITL smoke test; never targets hardware."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import time

from contracts.core.geometry import FrameId
from contracts.core.primitives import ResourceVersion, SchemaVersion
from contracts.core.quality import ComponentFreshness, FreshnessState
from contracts.core.time import TimePoint
from contracts.effects.vehicle import EffectEnvelope, ModeEffect
from contracts.vehicle.command import CommandPhase
from contracts.world.models import WorldSnapshot
from core.control_authority import ControlAuthority, ControlLease
from core.vehicle_execution import VehicleExecution
from core.vehicle_safety import SafetyLimits, VehicleSafetyPolicy
from infrastructure.transports.bytes import TcpByteTransport
from protocols.mavlink.codec import MavlinkCodec
from protocols.mavlink.constants import TYPE_QUADROTOR
from vehicles.multirotor.ardupilot_commands import ArduPilotCommandTranslator
from vehicles.multirotor.mavlink_port import ArduPilotCommandPort
from vehicles.multirotor.mavlink_state import ArduPilotTelemetryState
from vehicles.multirotor.session import ArduPilotSession


def now() -> TimePoint:
    return TimePoint(time.monotonic_ns(), datetime.now(timezone.utc), "sitl-host")


def later(point: TimePoint, delay_ns: int) -> TimePoint:
    return TimePoint(point.monotonic_ns + delay_ns,
                     point.utc + timedelta(microseconds=delay_ns // 1000), point.clock_domain_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-send", action="store_true", help="enable one unarmed GUIDED mode request to localhost SITL")
    args = parser.parse_args()
    if not args.allow_send:
        parser.error("--allow-send is required for this SITL command smoke test")
    transport = TcpByteTransport.connect("127.0.0.1", 5760, timeout_s=0.2)
    authority = ControlAuthority()
    codec = MavlinkCodec(source_system=250, source_component=191, target_system=1, target_component=1)
    translator = ArduPilotCommandTranslator(mode_ids={"GUIDED": 4})
    port = ArduPilotCommandPort(authority=authority, transport=transport, codec=codec,
                                translator=translator, now=now)
    session = ArduPilotSession(
        transport=transport, codec=codec, authority=authority, commands=port,
        link_timeout_ns=5_000_000_000,
        expected_vehicle_type=TYPE_QUADROTOR,
        state_factory=lambda session_id: ArduPilotTelemetryState(
            vehicle_id="sitl-copter", generation_id=str(session_id), link_session_id=session_id,
            source_system=1, source_component=1, max_sample_skew_ns=500_000_000,
            max_field_age_ns=5_000_000_000, link_timeout_ns=5_000_000_000,
        ),
        # Loopback SITL approximation only; not a physical capture clock.
        captured_at=lambda message, received: received,
    )
    try:
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and session.snapshot() is None:
            session.poll(now())
        state = session.snapshot()
        if state is None or session.session_id is None:
            print("FAIL: no SITL heartbeat")
            return 1
        if state.operation.armed:
            print("FAIL: SITL is already armed; refusing smoke command")
            return 1
        current = now()
        world = WorldSnapshot(
            SchemaVersion(1, 0), "sitl-world", ResourceVersion("sitl", 1), current,
            vehicle=state, freshness=(ComponentFreshness("vehicle", FreshnessState.FRESH),),
        )
        limits = SafetyLimits(
            max_request_ttl_ns=5_000_000_000, max_snapshot_age_ns=5_000_000_000,
            deadman_ns=1_000_000_000, min_altitude_m=0, max_altitude_m=10,
            max_takeoff_m=2, max_linear_mps=1, max_angular_rad_s=0.5,
            allowed_frames=frozenset({FrameId("odom")}), allowed_modes=frozenset({"GUIDED"}),
            min_x_m=-5, max_x_m=5, min_y_m=-5, max_y_m=5,
        )
        execution = VehicleExecution(port, authority, VehicleSafetyPolicy(limits), lambda: "sitl-mode-1")
        authority.grant(ControlLease("sitl-lease", "sitl-run", "sitl-action", later(current, 10_000_000_000)), current)
        authority.set_system_send(True)
        authority.set_action_send(True)
        request = EffectEnvelope(SchemaVersion(1, 0), "sitl-effect-1", "sitl-run", "sitl-action",
                                 current, later(current, 5_000_000_000), ModeEffect("GUIDED"))
        result = execution.dispatch(request, world, now())
        if result.receipt is None or result.receipt.phase is not CommandPhase.ACCEPTED:
            print(f"FAIL: admission {result.reason}")
            return 1
        sent = session.write_next(now())
        if sent is None or sent.phase is not CommandPhase.TRANSMITTED:
            print(f"FAIL: write {sent}")
            return 1
        command_id = result.receipt.command_id
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            session.poll(now())
            phase = port.status(command_id).phase
            if phase in (CommandPhase.ACKNOWLEDGED, CommandPhase.COMPLETED):
                print(f"PASS: localhost SITL GUIDED command phase={phase.value}, armed={session.snapshot().operation.armed}")
                return 0
            if phase in (CommandPhase.REJECTED, CommandPhase.UNKNOWN):
                print(f"FAIL: phase={phase.value}, reason={port.reasons.get(command_id)}")
                return 1
        print(f"FAIL: ACK timeout, phase={port.status(command_id).phase.value}")
        return 1
    finally:
        authority.set_system_send(False)
        session.close(now())


if __name__ == "__main__":
    raise SystemExit(main())
