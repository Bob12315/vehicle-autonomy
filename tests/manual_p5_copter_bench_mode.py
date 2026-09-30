"""Disarmed Copter USB bench: STABILIZE -> ACRO -> STABILIZE through Execution."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from itertools import count
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
from protocols.mavlink.constants import TYPE_QUADROTOR
from vehicles.multirotor.diagnostic import CopterBenchModeDiagnosticTranslator
from vehicles.multirotor.mavlink_port import ArduPilotCommandPort
from vehicles.multirotor.mavlink_state import ArduPilotTelemetryState
from vehicles.multirotor.session import ArduPilotSession


def now() -> TimePoint:
    return TimePoint(time.monotonic_ns(), datetime.now(timezone.utc), "usb-mode-host")


def later(point: TimePoint, delay_ns: int) -> TimePoint:
    return TimePoint(point.monotonic_ns + delay_ns,
                     point.utc + timedelta(microseconds=delay_ns // 1000), point.clock_domain_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--allow-mode-roundtrip", action="store_true")
    args = parser.parse_args()
    if not args.allow_mode_roundtrip:
        parser.error("explicit mode round-trip flag required")

    transport = SerialByteTransport.connect(args.port, timeout_s=0.2)
    authority = ControlAuthority()
    codec = MavlinkCodec(source_system=250, source_component=191, target_system=1, target_component=1)
    port = ArduPilotCommandPort(
        authority=authority, transport=transport, codec=codec,
        translator=CopterBenchModeDiagnosticTranslator(), now=now,
    )
    session = ArduPilotSession(
        transport=transport, codec=codec, authority=authority, commands=port,
        expected_vehicle_type=TYPE_QUADROTOR, link_timeout_ns=5_000_000_000,
        state_factory=lambda session_id: ArduPilotTelemetryState(
            vehicle_id="usb-copter-mode", generation_id=str(session_id), link_session_id=session_id,
            source_system=1, source_component=1, max_sample_skew_ns=500_000_000,
            max_field_age_ns=5_000_000_000, link_timeout_ns=5_000_000_000,
        ),
        # Diagnostic receive-time proxy; not a source capture clock.
        captured_at=lambda message, received: received,
    )
    serials = count(1)
    limits = SafetyLimits(
        max_request_ttl_ns=5_000_000_000, max_snapshot_age_ns=5_000_000_000,
        deadman_ns=1_000_000_000, min_altitude_m=0, max_altitude_m=1,
        max_takeoff_m=0.5, max_linear_mps=0.1, max_angular_rad_s=0.1,
        allowed_frames=frozenset({FrameId("odom")}),
        allowed_modes=frozenset({"STABILIZE", "ACRO"}),
        min_x_m=-1, max_x_m=1, min_y_m=-1, max_y_m=1,
    )
    execution = VehicleExecution(
        port, authority, VehicleSafetyPolicy(limits),
        lambda: f"usb-mode-command-{next(serials)}",
    )

    def send_mode(name: str, expected_id: int) -> None:
        state = session.snapshot()
        if state is None or state.operation.armed is not False:
            raise RuntimeError("mode request requires current disarmed state")
        current = now()
        world = WorldSnapshot(
            SchemaVersion(1, 0), "usb-mode-world", ResourceVersion("usb-mode", next(serials)),
            current, vehicle=state,
            freshness=(ComponentFreshness("vehicle", FreshnessState.FRESH),),
        )
        request = EffectEnvelope(
            SchemaVersion(1, 0), f"usb-mode-effect-{next(serials)}", "usb-mode-run",
            "usb-mode-action", current, later(current, 5_000_000_000), ModeEffect(name),
        )
        result = execution.dispatch(request, world, now())
        if result.receipt is None or result.receipt.phase is not CommandPhase.ACCEPTED:
            raise RuntimeError(f"{name} admission failed: {result.reason}")
        sent = session.write_next(now())
        if sent is None or sent.phase is not CommandPhase.TRANSMITTED:
            raise RuntimeError(f"{name} write failed: {sent}")
        command_id = result.receipt.command_id
        end = time.monotonic() + 6
        while time.monotonic() < end:
            session.poll(now())
            phase = port.status(command_id).phase
            if phase is CommandPhase.COMPLETED:
                observed = session.snapshot()
                if (observed is None or observed.operation.armed is not False
                        or observed.operation.native_mode != f"ARDUPILOT_CUSTOM_{expected_id}"):
                    raise RuntimeError(f"{name} completion without matching disarmed state")
                return
            if phase in (CommandPhase.REJECTED, CommandPhase.UNKNOWN):
                raise RuntimeError(f"{name} phase={phase.value}, reason={port.reasons.get(command_id)}")
        raise RuntimeError(f"{name} completion timeout: {port.status(command_id).phase.value}")

    roundtrip_started = False
    try:
        end = time.monotonic() + 15
        while time.monotonic() < end and session.snapshot() is None:
            session.poll(now())
        state = session.snapshot()
        if (state is None or session.session_id is None or state.operation.armed is not False
                or state.operation.native_mode != "ARDUPILOT_CUSTOM_0"):
            print("FAIL: requires a disarmed Copter already in STABILIZE")
            return 1
        current = now()
        authority.grant(ControlLease(
            "usb-mode-lease", "usb-mode-run", "usb-mode-action",
            later(current, 30_000_000_000),
        ), current)
        authority.set_system_send(True)
        authority.set_action_send(True)
        roundtrip_started = True
        send_mode("ACRO", 1)
        print("ACRO completed, armed=False")
        send_mode("STABILIZE", 0)
        print("PASS: STABILIZE -> ACRO -> STABILIZE completed, final armed=False")
        return 0
    finally:
        try:
            observed = session.snapshot()
            if (roundtrip_started and observed is not None
                    and observed.operation.native_mode == "ARDUPILOT_CUSTOM_1"
                    and observed.operation.armed is False and session.session_id is not None):
                send_mode("STABILIZE", 0)
        finally:
            authority.set_system_send(False)
            authority.set_action_send(False)
            session.close(now())


if __name__ == "__main__":
    raise SystemExit(main())
