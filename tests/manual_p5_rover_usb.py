"""Explicit MicoAir ArduRover USB diagnostic: repeat current HOLD mode only."""

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
from infrastructure.transports.bytes import SerialByteTransport
from protocols.mavlink.codec import MavlinkCodec
from protocols.mavlink.constants import TYPE_GROUND_ROVER
from vehicles.multirotor.mavlink_port import ArduPilotCommandPort
from vehicles.multirotor.mavlink_state import ArduPilotTelemetryState
from vehicles.multirotor.session import ArduPilotSession
from vehicles.rover.diagnostic import RoverHoldDiagnosticTranslator


def now() -> TimePoint:
    return TimePoint(time.monotonic_ns(), datetime.now(timezone.utc), "usb-host")


def later(point: TimePoint, delay_ns: int) -> TimePoint:
    return TimePoint(point.monotonic_ns + delay_ns,
                     point.utc + timedelta(microseconds=delay_ns // 1000), point.clock_domain_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="stable /dev/serial/by-id path")
    parser.add_argument("--allow-send", action="store_true", help="send one HOLD-to-HOLD request")
    args = parser.parse_args()
    if not args.allow_send:
        parser.error("--allow-send is required")
    transport = SerialByteTransport.connect(args.port, timeout_s=0.2)
    authority = ControlAuthority()
    codec = MavlinkCodec(source_system=250, source_component=191, target_system=1, target_component=1)
    translator = RoverHoldDiagnosticTranslator()
    port = ArduPilotCommandPort(authority=authority, transport=transport, codec=codec,
                                translator=translator, now=now)
    session = ArduPilotSession(
        transport=transport, codec=codec, authority=authority, commands=port,
        expected_vehicle_type=TYPE_GROUND_ROVER, link_timeout_ns=5_000_000_000,
        state_factory=lambda session_id: ArduPilotTelemetryState(
            vehicle_id="usb-rover", generation_id=str(session_id), link_session_id=session_id,
            source_system=1, source_component=1, max_sample_skew_ns=500_000_000,
            max_field_age_ns=5_000_000_000, link_timeout_ns=5_000_000_000,
        ),
        # USB receive-time proxy for this diagnostic only; source capture is unknown.
        captured_at=lambda message, received: received,
    )
    try:
        deadline = time.monotonic() + 30
        state = None
        while time.monotonic() < deadline:
            session.poll(now())
            state = session.snapshot()
            if state is not None and state.operation.native_mode == "ARDUPILOT_CUSTOM_4":
                break
        if state is None or session.session_id is None:
            print(f"FAIL: no Rover heartbeat; rejected_type={session.last_rejected_vehicle_type}")
            return 1
        if state.operation.native_mode != "ARDUPILOT_CUSTOM_4" or state.operation.armed is not False:
            print(f"FAIL: controller must be disarmed and already in HOLD; mode={state.operation.native_mode}, armed={state.operation.armed}")
            return 1
        current = now()
        world = WorldSnapshot(SchemaVersion(1, 0), "usb-world", ResourceVersion("usb", 1), current,
                              vehicle=state, freshness=(ComponentFreshness("vehicle", FreshnessState.FRESH),))
        limits = SafetyLimits(
            max_request_ttl_ns=5_000_000_000, max_snapshot_age_ns=5_000_000_000,
            deadman_ns=1_000_000_000, min_altitude_m=0, max_altitude_m=1,
            max_takeoff_m=0.5, max_linear_mps=0.1, max_angular_rad_s=0.1,
            allowed_frames=frozenset({FrameId("odom")}), allowed_modes=frozenset({"HOLD"}),
            min_x_m=-1, max_x_m=1, min_y_m=-1, max_y_m=1,
        )
        execution = VehicleExecution(port, authority, VehicleSafetyPolicy(limits), lambda: "usb-hold-command")
        authority.grant(ControlLease("usb-lease", "usb-run", "usb-action", later(current, 10_000_000_000)), current)
        authority.set_system_send(True)
        authority.set_action_send(True)
        request = EffectEnvelope(SchemaVersion(1, 0), "usb-hold-effect", "usb-run", "usb-action",
                                 current, later(current, 5_000_000_000), ModeEffect("HOLD"))
        result = execution.dispatch(request, world, now())
        if result.receipt is None or result.receipt.phase is not CommandPhase.ACCEPTED:
            print(f"FAIL: admission {result.reason}")
            return 1
        sent = session.write_next(now())
        if sent is None or sent.phase is not CommandPhase.TRANSMITTED:
            print(f"FAIL: write {sent}")
            return 1
        deadline = time.monotonic() + 6
        command_id = result.receipt.command_id
        while time.monotonic() < deadline:
            session.poll(now())
            phase = port.status(command_id).phase
            if phase is CommandPhase.COMPLETED:
                observed = session.snapshot()
                if (observed is None or observed.operation.armed is not False
                        or observed.operation.native_mode != "ARDUPILOT_CUSTOM_4"):
                    print("FAIL: completion without disarmed Rover HOLD state")
                    return 1
                print(f"PASS: Rover HOLD command phase={phase.value}, armed={observed.operation.armed}")
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
