"""Bare Copter controller bench: one fenced arm request, then disarm if accepted."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from itertools import count
import time

from contracts.core.geometry import FrameId
from contracts.core.primitives import ResourceVersion, SchemaVersion
from contracts.core.quality import ComponentFreshness, FreshnessState
from contracts.core.time import TimePoint
from contracts.effects.vehicle import ArmEffect, DisarmEffect, EffectEnvelope
from contracts.vehicle.command import CommandPhase
from contracts.world.models import WorldSnapshot
from core.control_authority import ControlAuthority, ControlLease
from core.vehicle_execution import VehicleExecution
from core.vehicle_safety import SafetyLimits, VehicleSafetyPolicy
from infrastructure.transports.bytes import SerialByteTransport
from protocols.mavlink.codec import MavlinkCodec
from protocols.mavlink.constants import TYPE_QUADROTOR
from vehicles.multirotor.diagnostic import CopterBenchArmDiagnosticTranslator
from vehicles.multirotor.mavlink_port import ArduPilotCommandPort
from vehicles.multirotor.mavlink_state import ArduPilotTelemetryState
from vehicles.multirotor.session import ArduPilotSession


def now() -> TimePoint:
    return TimePoint(time.monotonic_ns(), datetime.now(timezone.utc), "usb-bench-host")


def later(point: TimePoint, delay_ns: int) -> TimePoint:
    return TimePoint(point.monotonic_ns + delay_ns,
                     point.utc + timedelta(microseconds=delay_ns // 1000), point.clock_domain_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--bare-controller", action="store_true")
    parser.add_argument("--allow-arm-bench", action="store_true")
    args = parser.parse_args()
    if not args.bare_controller or not args.allow_arm_bench:
        parser.error("bare controller and explicit bench arm flags are required")

    transport = SerialByteTransport.connect(args.port, timeout_s=0.2)
    authority = ControlAuthority()
    codec = MavlinkCodec(source_system=250, source_component=191, target_system=1, target_component=1)
    port = ArduPilotCommandPort(
        authority=authority, transport=transport, codec=codec,
        translator=CopterBenchArmDiagnosticTranslator(), now=now,
    )
    session = ArduPilotSession(
        transport=transport, codec=codec, authority=authority, commands=port,
        expected_vehicle_type=TYPE_QUADROTOR, link_timeout_ns=5_000_000_000,
        state_factory=lambda session_id: ArduPilotTelemetryState(
            vehicle_id="usb-copter-bench", generation_id=str(session_id), link_session_id=session_id,
            source_system=1, source_component=1, max_sample_skew_ns=500_000_000,
            max_field_age_ns=5_000_000_000, link_timeout_ns=5_000_000_000,
        ),
        # Diagnostic receive-time proxy; no source capture-time guarantee.
        captured_at=lambda message, received: received,
    )
    notes: list[str] = []
    serials = count(1)
    limits = SafetyLimits(
        max_request_ttl_ns=5_000_000_000, max_snapshot_age_ns=5_000_000_000,
        deadman_ns=1_000_000_000, min_altitude_m=0, max_altitude_m=1,
        max_takeoff_m=0.5, max_linear_mps=0.1, max_angular_rad_s=0.1,
        allowed_frames=frozenset({FrameId("odom")}), allowed_modes=frozenset({"STABILIZE"}),
        min_x_m=-1, max_x_m=1, min_y_m=-1, max_y_m=1,
    )
    execution = VehicleExecution(
        port, authority, VehicleSafetyPolicy(limits),
        lambda: f"usb-bench-command-{next(serials)}",
    )

    def poll() -> None:
        for message in session.poll(now()):
            if message.get_type() == "STATUSTEXT":
                note = str(message.text).split("\0", 1)[0]
                if note and note not in notes:
                    notes.append(note)

    def dispatch(effect: ArmEffect | DisarmEffect) -> CommandPhase:
        current = now()
        state = session.snapshot()
        if state is None:
            raise RuntimeError("no current Copter state")
        world = WorldSnapshot(
            SchemaVersion(1, 0), "usb-bench-world", ResourceVersion("usb-bench", next(serials)),
            current, vehicle=state,
            freshness=(ComponentFreshness("vehicle", FreshnessState.FRESH),),
        )
        sequence = next(serials)
        request = EffectEnvelope(
            SchemaVersion(1, 0), f"usb-bench-effect-{sequence}", "usb-bench-run",
            "usb-bench-action", current, later(current, 5_000_000_000), effect,
        )
        result = execution.dispatch(request, world, now())
        if result.receipt is None or result.receipt.phase is not CommandPhase.ACCEPTED:
            raise RuntimeError(f"admission failed: {result.reason}")
        sent = session.write_next(now())
        if sent is None or sent.phase is not CommandPhase.TRANSMITTED:
            raise RuntimeError(f"write failed: {sent}")
        command_id = result.receipt.command_id
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            poll()
            phase = port.status(command_id).phase
            if phase in (CommandPhase.COMPLETED, CommandPhase.REJECTED, CommandPhase.UNKNOWN):
                if phase is CommandPhase.REJECTED:
                    print(f"{type(effect).__name__} rejected: {port.reasons.get(command_id)}")
                return phase
        return port.status(command_id).phase

    arm_attempted = False
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and session.snapshot() is None:
            poll()
        state = session.snapshot()
        if state is None or session.session_id is None:
            print(f"FAIL: no Copter heartbeat; rejected_type={session.last_rejected_vehicle_type}")
            return 1
        if state.operation.native_mode != "ARDUPILOT_CUSTOM_0" or state.operation.armed is not False:
            print("FAIL: bench requires disarmed Copter already in STABILIZE")
            return 1

        current = now()
        authority.grant(ControlLease(
            "usb-bench-lease", "usb-bench-run", "usb-bench-action",
            later(current, 30_000_000_000),
        ), current)
        authority.set_system_send(True)
        authority.set_action_send(True)
        arm_attempted = True
        arm_phase = dispatch(ArmEffect())
        if arm_phase is CommandPhase.COMPLETED:
            if session.snapshot() is None or session.snapshot().operation.armed is not True:
                print("FAIL: arm completion without armed heartbeat")
                return 1
            disarm_phase = dispatch(DisarmEffect())
            final = session.snapshot()
            if disarm_phase is not CommandPhase.COMPLETED or final is None or final.operation.armed is not False:
                print(f"FAIL: disarm phase={disarm_phase.value}")
                return 1
            print("PASS: bench arm and disarm completed; final armed=False")
            return 0
        if arm_phase is CommandPhase.REJECTED:
            end = time.monotonic() + 1
            while time.monotonic() < end:
                poll()
            final = session.snapshot()
            if final is None or final.operation.armed is not False:
                print("FAIL: rejected arm but disarmed state not confirmed")
                return 1
            disarm_phase = dispatch(DisarmEffect())
            final = session.snapshot()
            if disarm_phase is not CommandPhase.COMPLETED or final is None or final.operation.armed is not False:
                print(f"FAIL: explicit disarm phase={disarm_phase.value}")
                return 1
            print(f"PASS: pre-arm rejection and explicit disarm confirmed; final armed=False; notes={notes}")
            return 0
        print(f"FAIL: ambiguous arm phase={arm_phase.value}; notes={notes}")
        return 1
    finally:
        try:
            observed = session.snapshot()
            if (arm_attempted and observed is not None and observed.operation.armed is True
                    and session.session_id is not None):
                phase = dispatch(DisarmEffect())
                if phase is not CommandPhase.COMPLETED or session.snapshot().operation.armed is not False:
                    raise RuntimeError(f"emergency bench disarm unconfirmed: {phase.value}")
        finally:
            authority.set_system_send(False)
            authority.set_action_send(False)
            session.close(now())


if __name__ == "__main__":
    raise SystemExit(main())
