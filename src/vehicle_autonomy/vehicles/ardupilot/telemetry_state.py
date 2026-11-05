"""Read-only ArduPilot MAVLink telemetry to normalized VehicleState."""

from __future__ import annotations

from threading import Lock
from collections import deque

from vehicle_autonomy.contracts.core.geometry import FrameId, GeoPoint, Pose3, Quaternion, Twist3, Vector3
from vehicle_autonomy.contracts.core.primitives import LinkSessionId, ResourceVersion, SchemaVersion, VehicleId
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.core.stamped import Stamped
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.vehicle.models import (
    BatteryState, LinkStateSnapshot, VehicleHealth, VehicleOperation, VehicleStateSnapshot,
)
from vehicle_autonomy.world.transform.tree import rotate_vector
from vehicle_autonomy.vehicles.ardupilot.mavlink.telemetry import (
    AttitudeFrdNed, GlobalPositionInt, GpsFix, Heartbeat, LocalPositionNed,
    SystemPower, decode_telemetry,
)


from vehicle_autonomy.vehicles.ardupilot.coordinates import _ned_to_enu, _euler_frd_ned_to_flu_enu
from vehicle_autonomy.vehicles.ardupilot.telemetry_monitor import TelemetryMonitor


def _close_enough(first: TimePoint, second: TimePoint, limit_ns: int) -> bool:
    return first.clock_domain_id == second.clock_domain_id and abs(first.monotonic_ns - second.monotonic_ns) <= limit_ns


def _recent(sample: TimePoint, published: TimePoint, limit_ns: int) -> bool:
    return (sample.clock_domain_id == published.clock_domain_id
            and 0 <= published.monotonic_ns - sample.monotonic_ns <= limit_ns)


class ArduPilotTelemetryState:
    """Consumes parsed messages from an external receive-only source.

    This class never opens a link, sends a heartbeat, or constructs a command.
    The caller supplies capture/receive times; onboard boot time is not silently
    treated as local monotonic time.
    """

    def __init__(
        self, *, vehicle_id: VehicleId, generation_id: str, link_session_id: LinkSessionId,
        source_system: int, source_component: int, max_sample_skew_ns: int,
        max_field_age_ns: int, link_timeout_ns: int, frame_id: FrameId = FrameId("odom"),
    ) -> None:
        for name, value in (("source_system", source_system), ("source_component", source_component),
                            ("max_sample_skew_ns", max_sample_skew_ns), ("max_field_age_ns", max_field_age_ns),
                            ("link_timeout_ns", link_timeout_ns)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self._vehicle_id = VehicleId(vehicle_id)
        self._generation = ResourceVersion(generation_id, 0).generation_id
        self._link_session = LinkSessionId(link_session_id)
        self._source_system = source_system
        self._source_component = source_component
        self._frame = FrameId(frame_id)
        self._skew_ns = max_sample_skew_ns
        self._field_age_ns = max_field_age_ns
        self._link_timeout_ns = link_timeout_ns
        self._lock = Lock()
        self._revision = 0
        self._latest: VehicleStateSnapshot | None = None
        self._position: tuple[Vector3, Vector3, TimePoint] | None = None
        self._attitude: tuple[Quaternion, Vector3, TimePoint] | None = None
        self._global: tuple[GeoPoint, TimePoint] | None = None
        self._gps: tuple[int, TimePoint] | None = None
        self._power: tuple[BatteryState, TimePoint] | None = None
        self._heartbeat: tuple[VehicleOperation, TimePoint] | None = None
        self._last_received: TimePoint | None = None
        self._monitor = TelemetryMonitor(link_session_id=self._link_session,
                                        source_system=source_system, source_component=source_component,
                                        max_age_ns=max_field_age_ns, frame_id=str(self._frame))
        self._source_captures: dict[str, TimePoint] = {}
        self._positions=deque(maxlen=128);self._attitudes=deque(maxlen=128)

    def ingest(self, message: object, *, captured_at: TimePoint, received_at: TimePoint) -> bool:
        if not isinstance(captured_at, TimePoint) or not isinstance(received_at, TimePoint):
            raise TypeError("capture and receive times must be TimePoint")
        if captured_at.clock_domain_id == received_at.clock_domain_id and received_at < captured_at:
            raise ValueError("received_at cannot precede captured_at")
        try:
            source = (int(message.get_srcSystem()), int(message.get_srcComponent()))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("MAVLink message requires source IDs") from exc
        if source != (self._source_system, self._source_component):
            return False
        self.observe_telemetry(message, captured_at=captured_at, received_at=received_at)
        fact = decode_telemetry(message)
        if fact is None:
            return False
        with self._lock:
            if self._last_received is not None and (
                received_at.clock_domain_id == self._last_received.clock_domain_id
                and received_at < self._last_received
            ):
                raise ValueError("MAVLink receive time regressed")
            kind = message.get_type()
            # A receive event must not renew an old sensor sample or replace it
            # with reordered payload. Session source-clock regressions fail closed.
            if kind in ("LOCAL_POSITION_NED", "GLOBAL_POSITION_INT", "ATTITUDE", "GPS_RAW_INT"):
                previous = self._source_captures.get(kind)
                if previous is not None and captured_at.clock_domain_id == previous.clock_domain_id and captured_at <= previous:
                    return False
                self._source_captures[kind] = captured_at
            if isinstance(fact, LocalPositionNed):
                self._position = (
                    _ned_to_enu(fact.north_m, fact.east_m, fact.down_m),
                    _ned_to_enu(fact.velocity_north_mps, fact.velocity_east_mps, fact.velocity_down_mps),
                    captured_at,
                )
                self._positions.append(Stamped(self._frame,captured_at,self._position[0]))
            elif isinstance(fact, AttitudeFrdNed):
                self._attitude = (
                    _euler_frd_ned_to_flu_enu(fact.roll_rad, fact.pitch_rad, fact.yaw_rad),
                    Vector3(fact.roll_rate_rad_s, -fact.pitch_rate_rad_s, -fact.yaw_rate_rad_s),
                    captured_at,
                )
                self._attitudes.append(Stamped(self._frame,captured_at,self._attitude[0]))
            elif isinstance(fact, GlobalPositionInt):
                self._global = (GeoPoint(fact.latitude_e7 / 1e7, fact.longitude_e7 / 1e7,
                                         fact.altitude_mm / 1000), captured_at)
            elif isinstance(fact, GpsFix):
                self._gps = (fact.fix_type, captured_at)
            elif isinstance(fact, SystemPower):
                self._power = (BatteryState(
                    None if fact.voltage_mv == 65535 else fact.voltage_mv / 1000,
                    None if fact.current_centiamp == -1 else fact.current_centiamp / 100,
                    None if fact.remaining_percent == -1 else fact.remaining_percent,
                ), captured_at)
            elif isinstance(fact, Heartbeat):
                self._heartbeat = (VehicleOperation(
                    armed=bool(fact.base_mode & 128),
                    native_mode=f"ARDUPILOT_CUSTOM_{fact.custom_mode}",
                ), captured_at)
            self._last_received = received_at
            return True

    def note_rejected_telemetry(self, message: object, reason: str) -> None:
        with self._lock:
            sample = self._monitor.samples.get(message.get_type())
            if sample is not None:
                sample.observations += 1
                if reason == "duplicate":
                    sample.duplicates += 1
                else:
                    sample.out_of_order += 1

    def observe_telemetry(self, message: object, *, captured_at: TimePoint | None, received_at: TimePoint) -> None:
        """Receive diagnostics independently from control-qualified sample timing."""
        with self._lock:
            self._monitor.ingest(message, captured_at=captured_at, received_at=received_at)

    def telemetry_snapshot(self, at_time: TimePoint):
        with self._lock:
            return self._monitor.publish(at_time)

    def motion_history(self):
        from vehicle_autonomy.contracts.vehicle.telemetry import MotionTelemetryHistory
        with self._lock:
            return MotionTelemetryHistory(self._link_session,tuple(self._positions),tuple(self._attitudes))

    def local_reference(self):
        """No geodetic origin is retained by the generic LOCAL_POSITION_NED adapter."""
        return None

    def publish(self, published_at: TimePoint) -> VehicleStateSnapshot:
        if not isinstance(published_at, TimePoint):
            raise TypeError("published_at must be TimePoint")
        with self._lock:
            if self._latest is not None:
                if published_at.clock_domain_id != self._latest.published_at.clock_domain_id:
                    raise ValueError("publication clock domain changed")
                if published_at < self._latest.published_at:
                    raise ValueError("publication time regressed")
            if (self._last_received is not None
                    and self._last_received.clock_domain_id == published_at.clock_domain_id
                    and published_at < self._last_received):
                raise ValueError("publication cannot precede receive time")
            pose = None
            twist = None
            if self._position is not None and self._attitude is not None:
                position, linear, position_time = self._position
                orientation, angular_body_flu, attitude_time = self._attitude
                if _close_enough(position_time, attitude_time, self._skew_ns):
                    conservative_time = position_time if position_time < attitude_time else attitude_time
                    pose = Stamped(self._frame, conservative_time, Pose3(position, orientation))
                    angular_enu = rotate_vector(orientation, angular_body_flu)
                    twist = Stamped(self._frame, conservative_time, Twist3(linear, angular_enu))
            global_position = None
            if self._global is not None and self._gps is not None:
                location, location_time = self._global
                fix, fix_time = self._gps
                if fix >= 3 and _close_enough(location_time, fix_time, self._skew_ns):
                    conservative_time = location_time if location_time < fix_time else fix_time
                    global_position = Stamped("earth", conservative_time, location)
            operation = VehicleOperation()
            quality = QualityState.UNAVAILABLE
            if self._heartbeat is not None:
                heartbeat, heartbeat_time = self._heartbeat
                if _recent(heartbeat_time, published_at, self._field_age_ns):
                    operation = heartbeat
                    quality = QualityState.VALID
                else:
                    quality = QualityState.INVALID
            elif self._last_received is not None:
                quality = QualityState.DEGRADED
            battery = None
            if self._power is not None and _recent(self._power[1], published_at, self._field_age_ns):
                battery = self._power[0]
            next_revision = self._revision + 1
            candidate = VehicleStateSnapshot(
                SchemaVersion(1, 1), self._vehicle_id,
                ResourceVersion(self._generation, next_revision), published_at,
                VehicleHealth(quality), pose, twist, global_position, operation, battery,
                self._monitor.publish(published_at),
            )
            self._revision = next_revision
            self._latest = candidate
            return candidate

    def snapshot(self) -> VehicleStateSnapshot | None:
        with self._lock:
            return self._latest

    def link_snapshot(self, at_time: TimePoint) -> LinkStateSnapshot:
        if not isinstance(at_time, TimePoint):
            raise TypeError("at_time must be TimePoint")
        with self._lock:
            connected = self._last_received is not None and _recent(self._last_received, at_time, self._link_timeout_ns)
            return LinkStateSnapshot(
                SchemaVersion(1, 0), self._vehicle_id,
                ResourceVersion(self._generation, self._revision), at_time,
                connected, QualityState.VALID if connected else QualityState.UNAVAILABLE,
                self._link_session, self._last_received,
            )
