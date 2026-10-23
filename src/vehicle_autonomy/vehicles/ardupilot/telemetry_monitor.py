"""Normalize AP diagnostics without granting control freshness or authority."""
from dataclasses import dataclass

from vehicle_autonomy.contracts.core.geometry import GeoPoint, Vector3
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.vehicle.telemetry import (
    AckTelemetry, AttitudeTelemetry, EkfTelemetry, GpsTelemetry, PositionTelemetry,
    PowerTelemetry, StatusTextTelemetry, TelemetryAvailability as Availability,
    TelemetryField, VehicleIdentity, VehicleTelemetrySnapshot,
)
from vehicle_autonomy.vehicles.ardupilot.coordinates import _ned_to_enu, _euler_frd_ned_to_flu_enu
from vehicle_autonomy.vehicles.ardupilot.mavlink.telemetry import (
    AttitudeFrdNed, CommandAck, EkfStatus, GlobalPositionInt, GpsFix, Heartbeat,
    LocalPositionNed, StatusText, SystemPower, decode_telemetry,
)

MESSAGE_TYPES = ("HEARTBEAT", "ATTITUDE", "GLOBAL_POSITION_INT", "LOCAL_POSITION_NED",
                 "GPS_RAW_INT", "EKF_STATUS_REPORT", "SYS_STATUS", "COMMAND_ACK", "STATUSTEXT")
TIMED_TYPES = frozenset(("ATTITUDE", "GLOBAL_POSITION_INT", "LOCAL_POSITION_NED", "GPS_RAW_INT"))


@dataclass
class _Sample:
    value: object = None
    frame: str | None = None
    capture: object = None
    receive: object = None
    observations: int = 0
    duplicates: int = 0
    out_of_order: int = 0
    invalid: int = 0
    bad: bool = False


def _normalize(fact, frame):
    if isinstance(fact, Heartbeat):
        return VehicleIdentity(fact.vehicle_type, fact.autopilot, fact.custom_mode,
                               bool(fact.base_mode & 128), fact.system_status), None
    if isinstance(fact, AttitudeFrdNed):
        return AttitudeTelemetry(_euler_frd_ned_to_flu_enu(fact.roll_rad, fact.pitch_rad, fact.yaw_rad),
                                 Vector3(fact.roll_rate_rad_s, -fact.pitch_rate_rad_s, -fact.yaw_rate_rad_s)), frame
    if isinstance(fact, LocalPositionNed):
        return PositionTelemetry(_ned_to_enu(fact.north_m, fact.east_m, fact.down_m),
                                 _ned_to_enu(fact.velocity_north_mps, fact.velocity_east_mps, fact.velocity_down_mps)), frame
    if isinstance(fact, GlobalPositionInt):
        velocity = None if fact.velocity_ned_cms is None else _ned_to_enu(*(v / 100 for v in fact.velocity_ned_cms))
        return PositionTelemetry(None, velocity, GeoPoint(fact.latitude_e7 / 1e7, fact.longitude_e7 / 1e7,
                                                          fact.altitude_mm / 1000)), "earth"
    if isinstance(fact, GpsFix):
        return GpsTelemetry(fact.fix_type, None if fact.satellites in (None, 255) else fact.satellites,
                            None if fact.eph in (None, 65535) else fact.eph / 100,
                            None if fact.epv in (None, 65535) else fact.epv / 100), "earth"
    if isinstance(fact, EkfStatus):
        return EkfTelemetry(fact.flags, *fact.variances), None
    if isinstance(fact, SystemPower):
        value = PowerTelemetry(None if fact.voltage_mv == 65535 else fact.voltage_mv / 1000,
                               None if fact.current_centiamp == -1 else fact.current_centiamp / 100,
                               None if fact.remaining_percent == -1 else fact.remaining_percent)
        if value.voltage_v is not None and value.voltage_v < 0:
            raise ValueError("invalid voltage")
        if value.remaining_percent is not None and not 0 <= value.remaining_percent <= 100:
            raise ValueError("invalid remaining battery")
        return value, None
    if isinstance(fact, CommandAck):
        return AckTelemetry(fact.command, fact.result, None if fact.progress in (None, 255) else fact.progress), None
    if isinstance(fact, StatusText):
        return StatusTextTelemetry(fact.severity, fact.text, fact.message_id, fact.chunk_sequence), None
    raise ValueError("unsupported telemetry fact")


class TelemetryMonitor:
    def __init__(self, *, link_session_id, source_system, source_component, max_age_ns, frame_id):
        self.session_id = link_session_id
        self.source = source_system, source_component
        self.max_age_ns = max_age_ns
        self.frame = frame_id
        self.samples = {kind: _Sample() for kind in MESSAGE_TYPES}

    def ingest(self, message, *, captured_at, received_at):
        if (message.get_srcSystem(), message.get_srcComponent()) != self.source:
            return
        kind = message.get_type()
        if kind not in self.samples:
            return
        sample = self.samples[kind]
        sample.observations += 1
        capture = captured_at if kind in TIMED_TYPES else None
        try:
            value, frame = _normalize(decode_telemetry(message), self.frame)
            if capture is not None:
                if capture.clock_domain_id != received_at.clock_domain_id or capture > received_at:
                    raise ValueError("unqualified capture clock")
                if sample.capture is not None:
                    if capture.clock_domain_id != sample.capture.clock_domain_id:
                        raise ValueError("capture clock changed")
                    if capture <= sample.capture:
                        if capture == sample.capture:
                            sample.duplicates += 1
                        else:
                            sample.out_of_order += 1
                        return
        except (AttributeError, ValueError, TypeError, OverflowError):
            sample.invalid += 1
            sample.bad = True
            return
        sample.value, sample.frame = value, frame
        sample.capture, sample.receive, sample.bad = capture, received_at, False

    def publish(self, at_time):
        result = []
        for kind, sample in self.samples.items():
            def recent(stamp):
                return (stamp is not None and stamp.clock_domain_id == at_time.clock_domain_id
                        and 0 <= at_time.monotonic_ns - stamp.monotonic_ns <= self.max_age_ns)
            fresh = recent(sample.receive)
            quality = QualityState.UNAVAILABLE
            if sample.bad:
                availability, quality = Availability.INVALID, QualityState.INVALID
            elif sample.value is None:
                availability = Availability.MISSING
            elif not fresh or (sample.capture is not None and not recent(sample.capture)):
                availability, quality = Availability.STALE, QualityState.INVALID
            elif sample.capture is None:
                availability, quality = Availability.UNKNOWN_CAPTURE_TIME, QualityState.DEGRADED
            else:
                availability, quality = Availability.VALID, QualityState.VALID
            # Keep stale values for diagnostics, explicitly marked; invalid values
            # are never presented as usable values. Consumers cannot infer safety.
            result.append(TelemetryField(kind, availability, quality,
                                         None if sample.bad else sample.value, sample.frame,
                                         sample.capture, sample.receive, fresh, sample.observations,
                                         sample.duplicates, sample.out_of_order, sample.invalid))
        return VehicleTelemetrySnapshot(self.session_id, *self.source, at_time, tuple(result))
