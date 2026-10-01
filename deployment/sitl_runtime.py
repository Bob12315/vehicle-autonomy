"""Single-threaded, explicitly started localhost Copter SITL composition."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import time
from uuid import uuid4

from application.mission_service import MissionService
from contracts.core.primitives import RunId, SchemaVersion
from contracts.core.time import TimePoint
from contracts.decision import EffectPhase, EffectResult, MissionPlan, MissionStep
from contracts.effects.vehicle import ArmEffect, DisarmEffect, EffectEnvelope
from contracts.vehicle.command import CancelCommandRequest, CommandPhase
from contracts.vehicle.ports import VehicleCapabilities
from core.action_registry import ActionRegistry
from core.control_authority import ControlAuthority, ControlLease
from core.mission import MissionValidator
from core.mission_runtime import MissionRuntime, RunStatus
from core.sitl_mode_action import (
    SITL_ARM_SPEC, SITL_DISARM_SPEC, SITL_MODE_SPEC, SitlArmAction,
    SitlDisarmAction, SitlModeAction, SitlModeParameters,
)
from core.vehicle_execution import VehicleExecution
from core.vehicle_safety import VehicleSafetyPolicy
from infrastructure.transports.bytes import TcpByteTransport
from protocols.mavlink.codec import MavlinkCodec
from protocols.mavlink.constants import TYPE_QUADROTOR
from runtime.sitl import SitlProfile
from vehicles.multirotor.mavlink_port import ArduPilotCommandPort
from vehicles.multirotor.mavlink_state import ArduPilotTelemetryState
from vehicles.multirotor.session import ArduPilotSession
from vehicles.multirotor.sitl_guard import (
    SitlArmTranslator, SitlModeTranslator, disarmed_mode_write_guard,
    sitl_arm_write_guard,
)
from world_model import FreshnessLimits, WorldModel


def later(point: TimePoint, ns: int) -> TimePoint:
    return TimePoint(point.monotonic_ns + ns,
                     point.utc + timedelta(microseconds=ns // 1000), point.clock_domain_id)


class SitlRuntime:
    def __init__(self, profile: SitlProfile, *, allow_send: bool = False,
                 transport=None, clock=None, event_sink=None,
                 sitl_version: str | None = None, arm_then_disarm: bool = False,
                 allow_arm: bool = False) -> None:
        if not isinstance(profile, SitlProfile):
            raise TypeError("validated SITL profile required")
        if arm_then_disarm and (not allow_send or not allow_arm or profile.arm_ready_wait_ns <= 0):
            raise ValueError("SITL arm Mission requires explicit SEND, arm permission and arm profile")
        self.profile = profile
        self.clock = clock or (lambda: TimePoint(time.monotonic_ns(), datetime.now(timezone.utc),
                                                 profile.clock_domain_id))
        self.events: list[dict] = []
        self._event_sink = event_sink
        self.authority = ControlAuthority()
        self._allow_send = allow_send
        self._arm_then_disarm = arm_then_disarm
        self._closed = False
        self._last_cycle: TimePoint | None = None
        self._started_at: TimePoint | None = None
        self._runtime: MissionRuntime | None = None
        self._run_id: RunId | None = None
        self._effects: dict[str, tuple[object, str | None]] = {}
        self._results: dict[str, EffectResult] = {}
        self._fault: str | None = None
        self._restart_session_required: str | None = None
        self._sitl_version: str | None = sitl_version
        self._disarm_cleanup: str | None = None
        self._cleanup_command_id: str | None = None
        self._world = WorldModel(uuid4().hex, FreshnessLimits(
            profile.safety.max_snapshot_age_ns, profile.safety.max_snapshot_age_ns,
            profile.safety.max_snapshot_age_ns))
        self._transport = transport or TcpByteTransport.connect(
            profile.host, profile.port, timeout_s=profile.read_timeout_ns / 1e9)
        self._codec = MavlinkCodec(source_system=250, source_component=191,
                                  target_system=profile.target_system,
                                  target_component=profile.target_component)
        self._port = ArduPilotCommandPort(
            authority=self.authority, transport=self._transport, codec=self._codec,
            translator=(SitlArmTranslator if arm_then_disarm else SitlModeTranslator)(
                mode_ids={profile.mode: profile.mode_id}),
            now=self.clock,
            write_guard=self._write_guard,
        )
        self._session = ArduPilotSession(
            transport=self._transport, codec=self._codec, authority=self.authority,
            commands=self._port, link_timeout_ns=profile.link_timeout_ns,
            expected_vehicle_type=TYPE_QUADROTOR,
            state_factory=lambda session_id: ArduPilotTelemetryState(
                vehicle_id=profile.vehicle_id, generation_id=str(session_id),
                link_session_id=session_id, source_system=profile.target_system,
                source_component=profile.target_component,
                max_sample_skew_ns=500_000_000,
                max_field_age_ns=profile.safety.max_snapshot_age_ns,
                link_timeout_ns=profile.link_timeout_ns),
            # Loopback simulation receive-time proxy, never a vehicle capture clock.
            captured_at=lambda message, received: received,
        )
        self._execution = VehicleExecution(self._port, self.authority,
                                           VehicleSafetyPolicy(profile.safety),
                                           lambda: f"command:{uuid4().hex}")
        config_digest = hashlib.sha256(json.dumps(
            asdict(profile), sort_keys=True,
            default=lambda value: sorted(map(str, value)) if isinstance(value, frozenset) else str(value),
        ).encode()).hexdigest()
        self._emit("configured", allow_send=allow_send, allow_arm=allow_arm,
                   mission="arm_then_disarm" if arm_then_disarm else "mode_only",
                   host=profile.host, port=profile.port,
                   mode=profile.mode, clock_domain=profile.clock_domain_id,
                   capture_time="loopback_receive_proxy", config_sha256=config_digest,
                   sitl_version=sitl_version, version_source="operator" if sitl_version else "unreported")

    def _write_guard(self, command) -> str | None:
        state = self._session.snapshot()
        reason = (sitl_arm_write_guard(command, state, self.profile.mode, self.profile.mode_id)
                  if self._arm_then_disarm else
                  disarmed_mode_write_guard(command, state, self.profile.mode))
        if reason is not None:
            return reason
        try:
            age = self.clock().elapsed_ns_since(self._session.last_heartbeat_received_at)
        except (TypeError, ValueError):
            return "heartbeat_clock_invalid"
        if age < 0 or age > self.profile.safety.max_snapshot_age_ns:
            return "heartbeat_stale"
        return None

    def _emit(self, event: str, **fields) -> None:
        item = {"event": event, "at_monotonic_ns": self.clock().monotonic_ns,
                "run_id": None if self._run_id is None else str(self._run_id), **fields}
        self.events.append(item)
        if self._event_sink is not None:
            self._event_sink(item)

    def get_status(self) -> dict:
        update = None if self._runtime is None else self._runtime.view()
        snapshot = self._world.snapshot()
        return {
            "run_id": None if self._run_id is None else str(self._run_id),
            "status": ("FAILED" if self._fault is not None else "IDLE") if update is None else update.status.value,
            "error": self._fault or (None if update is None else update.error),
            "link_session_id": None if self._session.session_id is None else str(self._session.session_id),
            "snapshot_version": None if snapshot is None else snapshot.version.revision,
            "vehicle_frame": None if snapshot is None or snapshot.vehicle is None or
                                  snapshot.vehicle.reported_pose is None else str(snapshot.vehicle.reported_pose.frame_id),
            "vehicle_quality": None if snapshot is None or snapshot.vehicle is None else snapshot.vehicle.health.quality.value,
            "armed": None if snapshot is None or snapshot.vehicle is None else snapshot.vehicle.operation.armed,
            "step_id": None if update is None else update.step_id,
            "disarm_cleanup": self._disarm_cleanup,
            "sitl_version": self._sitl_version,
            "freshness": {} if snapshot is None else {item.component_id: item.state.value for item in snapshot.freshness},
            "effects": {key: {"phase": value.phase.value, "command_id": value.command_id,
                               "link_session_id": value.link_session_id, "reason": value.reason}
                        for key, value in self._results.items()},
        }

    def start_mission(self) -> dict:
        if self._closed or self._fault is not None or (self._runtime is not None and
                self._runtime.view().status in (RunStatus.RUNNING, RunStatus.EXITING)):
            raise RuntimeError("runtime closed, faulted or Mission already running")
        if self._restart_session_required is not None and self._restart_session_required == self._session.session_id:
            raise RuntimeError("in-flight cancelled mode requires a new link session")
        snapshot = self._world.snapshot()
        if snapshot is None or snapshot.vehicle is None or self._session.session_id is None:
            raise RuntimeError("fresh SITL vehicle state required")
        if snapshot.vehicle.operation.armed:
            raise RuntimeError("SITL vehicle must be disarmed")
        now = self.clock()
        if now.elapsed_ns_since(snapshot.published_at) > self.profile.safety.max_snapshot_age_ns:
            raise RuntimeError("SITL world state is stale")
        self._effects.clear()
        self._results.clear()
        self._disarm_cleanup = None
        self._cleanup_command_id = None
        self._run_id = RunId(f"sitl:{uuid4().hex}")
        registry = ActionRegistry()
        registry.register_typed(SITL_MODE_SPEC, SitlModeAction())
        parameters = SitlModeParameters(self.profile.mode, self.profile.mode_id)
        steps = [MissionStep("mode", SITL_MODE_SPEC.name, parameters)]
        if self._arm_then_disarm:
            registry.register_typed(SITL_ARM_SPEC, SitlArmAction())
            registry.register_typed(SITL_DISARM_SPEC, SitlDisarmAction())
            steps.extend((MissionStep("arm", SITL_ARM_SPEC.name, parameters),
                          MissionStep("disarm", SITL_DISARM_SPEC.name, parameters)))
        plan = MissionPlan("sitl-arm-cycle" if self._arm_then_disarm else "sitl-unarmed-mode", tuple(steps))
        compiled = MissionValidator(registry).compile(plan, VehicleCapabilities())
        self._runtime = MissionRuntime(compiled, self._world.reader(), self._run_id,
                                       max_snapshot_age_ns=self.profile.safety.max_snapshot_age_ns)
        self._started_at = now
        if self._allow_send:
            self.authority.grant(ControlLease(f"lease:{uuid4().hex}", self._run_id,
                f"{self._run_id}:mode:1", later(now, self.profile.lease_ns)), now)
            self.authority.set_system_send(True)
            self.authority.set_action_send(True)
        self._emit("mission_started", send_enabled=self._allow_send,
                   link_session_id=str(self._session.session_id))
        return self.get_status()

    def _authorize_effect(self, envelope, now: TimePoint) -> None:
        if not self._allow_send:
            return
        current = self.authority.lease
        if current is not None and current.action_instance_id == envelope.action_instance_id:
            return
        if not self._arm_then_disarm:
            raise RuntimeError("unexpected Action lease scope")
        expected_previous = {"arm": "mode", "disarm": "arm"}
        step_id = str(envelope.action_instance_id).split(":")[-2]
        previous = expected_previous.get(step_id)
        if previous is None or not any(
            result.action_instance_id == f"{self._run_id}:{previous}:1"
            and result.phase is EffectPhase.COMPLETED for result in self._results.values()
        ):
            raise RuntimeError("previous Action completion required for new lease")
        self.authority.grant(ControlLease(f"lease:{uuid4().hex}", self._run_id,
            envelope.action_instance_id, later(now, self.profile.lease_ns)), now)
        self.authority.set_system_send(True)
        self.authority.set_action_send(True)
        self._emit("action_authorized", action_instance_id=str(envelope.action_instance_id),
                   link_session_id=str(self._session.session_id))

    def _record(self, envelope, phase: EffectPhase, command_id=None, reason=None) -> None:
        result = EffectResult(str(envelope.effect_id), str(envelope.action_instance_id), phase,
                              None if command_id is None else str(command_id),
                              None if self._session.session_id is None else str(self._session.session_id), reason)
        if self._results.get(result.effect_id) == result:
            return
        self._results[result.effect_id] = result
        self._runtime.record_effect_result(result)
        self._emit("effect_result", action_instance_id=result.action_instance_id,
                   effect_id=result.effect_id, command_id=result.command_id,
                   link_session_id=result.link_session_id, phase=phase.value, reason=reason)

    def _fault_run(self, reason: str) -> None:
        if self._fault is None:
            self._fault = reason
            self._emit("fault", reason=reason)
        self.authority.set_action_send(False)
        self.authority.set_system_send(False)
        self.authority.revoke()
        if self._runtime is not None:
            self._runtime.abort(reason)

    def cycle(self) -> dict:
        if self._closed:
            raise RuntimeError("runtime closed")
        now = self.clock()
        if self._last_cycle is not None and now.elapsed_ns_since(self._last_cycle) > 2 * self.profile.period_ns:
            self._fault_run("cycle_deadline_missed")
        self._last_cycle = now
        try:
            messages = self._session.poll(now)
            for message in messages:
                if message.get_type() == "STATUSTEXT":
                    reported = message.text
                    if isinstance(reported, bytes):
                        reported = reported.decode("utf-8", errors="replace")
                    reported = str(reported).strip("\x00")
                    self._emit("vehicle_notice", severity=int(message.severity), message=reported)
                    if "ArduCopter V" in reported and reported != self._sitl_version:
                        self._sitl_version = reported
                        self._emit("sitl_version", reported=reported)
        except (OSError, ConnectionError) as exc:
            self._fault_run(f"transport_disconnected:{type(exc).__name__}")
        now = self.clock()
        self._world.update_vehicle(self._session.snapshot())
        snapshot = self._world.publish(now)
        self._emit("snapshot", snapshot_version=snapshot.version.revision,
                   published_at_ns=snapshot.published_at.monotonic_ns,
                   vehicle_state_at_ns=None if snapshot.vehicle is None else snapshot.vehicle.published_at.monotonic_ns,
                   heartbeat_received_at_ns=None if self._session.last_heartbeat_received_at is None
                   else self._session.last_heartbeat_received_at.monotonic_ns,
                   vehicle_freshness=snapshot.freshness[0].state.value,
                   frame=None if snapshot.vehicle is None or snapshot.vehicle.reported_pose is None
                   else str(snapshot.vehicle.reported_pose.frame_id),
                   quality=None if snapshot.vehicle is None else snapshot.vehicle.health.quality.value)
        active = self._runtime is not None and self._runtime.view().status in (RunStatus.RUNNING, RunStatus.EXITING)
        if active and self._session.session_id is None:
            self._fault_run("link_disconnected")
        if active and snapshot.vehicle is None:
            self._fault_run("vehicle_state_stale")
        if active and self._started_at is not None and now.elapsed_ns_since(self._started_at) > self.profile.mission_timeout_ns:
            self._fault_run("mission_timeout")
        if self._runtime is not None and self._runtime.view().status in (RunStatus.RUNNING, RunStatus.EXITING):
            update = self._runtime.tick(now)
            for envelope in update.effects:
                self._effects[str(envelope.effect_id)] = (envelope, None)
                self._record(envelope, EffectPhase.REQUESTED)
                self._authorize_effect(envelope, now)
                dispatch = self._execution.dispatch(envelope, snapshot, now)
                if dispatch.receipt is None or dispatch.receipt.phase is CommandPhase.REJECTED:
                    self._record(envelope, EffectPhase.REJECTED, reason=dispatch.reason)
                else:
                    self._effects[str(envelope.effect_id)] = (envelope, str(dispatch.receipt.command_id))
                    self._record(envelope, EffectPhase.ACCEPTED, dispatch.receipt.command_id)
        self._execution.tick(now)
        if self._session.session_id is not None and self._fault is None:
            self._session.write_next(self.clock())
        phases = {phase.value: EffectPhase(phase.value) for phase in CommandPhase}
        for envelope, command_id in tuple(self._effects.values()):
            if command_id is None:
                continue
            status = self._port.status(command_id)
            if status is not None:
                self._record(envelope, phases[status.phase.value], command_id,
                             self._port.reasons.get(command_id))
        return self.get_status()

    def cancel_mission(self) -> dict:
        if self._runtime is not None:
            self._runtime.cancel()
            now = self.clock()
            for envelope, command_id in self._effects.values():
                if command_id is not None:
                    status = self._port.status(command_id)
                    if status is not None and status.phase in (CommandPhase.ACCEPTED, CommandPhase.TRANSMITTED,
                                                                CommandPhase.ACKNOWLEDGED):
                        if (self._arm_then_disarm and isinstance(envelope.effect, (ArmEffect, DisarmEffect))
                                and status.phase in (CommandPhase.TRANSMITTED, CommandPhase.ACKNOWLEDGED)):
                            # Its outcome may change the armed state after cancellation.
                            # Keep the receiver tracking the ACK and later heartbeat.
                            self._restart_session_required = self._session.session_id
                            continue
                        if status.phase is CommandPhase.TRANSMITTED:
                            self._restart_session_required = self._session.session_id
                        self._port.cancel(CancelCommandRequest(command_id, now))
                        self._record(envelope, EffectPhase.CANCELLED, command_id, "mission_cancelled")
            if self._runtime.view().status is RunStatus.EXITING:
                self._runtime.tick(now)
                if self._runtime.view().status is RunStatus.EXITING:
                    self._runtime.abort("cancel_exit_unconfirmed")
            self.authority.set_action_send(False)
            self.authority.set_system_send(False)
            self.authority.revoke()
            self._emit("mission_cancelled")
        return self.get_status()

    def _try_cleanup_disarm(self) -> None:
        """One bounded, fenced disarm attempt for an armed SITL after cancellation/failure."""
        if not self._arm_then_disarm or self._run_id is None:
            return
        deadline = time.monotonic_ns() + self.profile.safety.max_request_ttl_ns
        while time.monotonic_ns() < deadline:
            now = self.clock()
            try:
                self._session.poll(now)
            except (OSError, ConnectionError):
                self._disarm_cleanup = "UNCONFIRMED_LINK_LOST"
                break
            now = self.clock()
            self._world.update_vehicle(self._session.snapshot())
            world = self._world.publish(now)
            state = world.vehicle
            if state is None or self._session.session_id is None:
                self._disarm_cleanup = "UNCONFIRMED_STATE_OR_LINK"
                break
            pending_arm = any(
                isinstance(envelope.effect, ArmEffect) and command_id is not None
                and self._port.status(command_id).phase in (CommandPhase.TRANSMITTED, CommandPhase.ACKNOWLEDGED)
                for envelope, command_id in self._effects.values()
            )
            unknown_arm = any(
                isinstance(envelope.effect, ArmEffect) and command_id is not None
                and self._port.status(command_id).phase is CommandPhase.UNKNOWN
                for envelope, command_id in self._effects.values()
            )
            if unknown_arm:
                self._disarm_cleanup = "UNCONFIRMED_ARM_OUTCOME"
                break
            if not state.operation.armed and not pending_arm:
                self._disarm_cleanup = "CONFIRMED"
                break
            disarm_command = self._cleanup_command_id
            if disarm_command is None:
                for envelope, command_id in self._effects.values():
                    if isinstance(envelope.effect, DisarmEffect) and command_id is not None:
                        phase = self._port.status(command_id).phase
                        if phase in (CommandPhase.TRANSMITTED, CommandPhase.ACKNOWLEDGED, CommandPhase.COMPLETED):
                            disarm_command = command_id
                            break
            if state.operation.armed and disarm_command is None:
                action_id = f"{self._run_id}:cleanup:1"
                self.authority.grant(ControlLease(f"lease:{uuid4().hex}", self._run_id,
                    action_id, later(now, self.profile.safety.max_request_ttl_ns)), now)
                self.authority.set_system_send(True)
                self.authority.set_action_send(True)
                envelope = EffectEnvelope(SchemaVersion(1, 0), f"{self._run_id}:cleanup-disarm",
                    self._run_id, action_id, now,
                    later(now, self.profile.safety.max_request_ttl_ns), DisarmEffect())
                result = self._execution.dispatch(envelope, world, now)
                if result.receipt is None or result.receipt.phase is not CommandPhase.ACCEPTED:
                    self._disarm_cleanup = f"UNCONFIRMED_{result.reason or 'rejected'}"
                    break
                self._cleanup_command_id = str(result.receipt.command_id)
                disarm_command = self._cleanup_command_id
                self._emit("cleanup_disarm_requested", effect_id=str(envelope.effect_id),
                           command_id=disarm_command, link_session_id=str(self._session.session_id))
            if disarm_command is not None:
                phase = self._port.status(disarm_command).phase
                if phase in (CommandPhase.UNKNOWN, CommandPhase.REJECTED, CommandPhase.CANCELLED):
                    self._disarm_cleanup = f"UNCONFIRMED_{phase.value}"
                    break
                self._session.write_next(self.clock())
            time.sleep(self.profile.period_ns / 1e9)
        if self._disarm_cleanup is None:
            self._disarm_cleanup = "UNCONFIRMED_TIMEOUT"
        self._emit("cleanup_disarm_result", result=self._disarm_cleanup,
                   command_id=self._cleanup_command_id)

    def shutdown(self) -> dict:
        if not self._closed:
            if self._runtime is not None and self._runtime.view().status in (RunStatus.RUNNING, RunStatus.EXITING):
                self.cancel_mission()
            self._try_cleanup_disarm()
            self.authority.set_action_send(False)
            self.authority.set_system_send(False)
            self.authority.revoke()
            self._session.close(self.clock())
            self._closed = True
            self._emit("shutdown", stop="no_motion_stream")
        return self.get_status()


def run_sitl(profile: SitlProfile, *, allow_send: bool = False, event_sink=None,
             sitl_version: str | None = None, arm_then_disarm: bool = False,
             allow_arm: bool = False) -> dict:
    runtime = SitlRuntime(profile, allow_send=allow_send, event_sink=event_sink,
                          sitl_version=sitl_version, arm_then_disarm=arm_then_disarm,
                          allow_arm=allow_arm)
    service = MissionService(runtime)
    try:
        warmup_start = time.monotonic_ns()
        warmup_deadline = warmup_start + max(profile.link_timeout_ns * 2,
                                             profile.arm_ready_wait_ns if arm_then_disarm else 0)
        while time.monotonic_ns() < warmup_deadline:
            runtime.cycle()
            if service.get_status()["vehicle_quality"] == "VALID" and (
                not arm_then_disarm or time.monotonic_ns() - warmup_start >= profile.arm_ready_wait_ns
            ):
                break
            time.sleep(profile.period_ns / 1e9)
        service.start_mission()
        while True:
            start = time.monotonic_ns()
            status = runtime.cycle()
            if status["status"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            time.sleep(max(0, (profile.period_ns - (time.monotonic_ns() - start)) / 1e9))
    except KeyboardInterrupt:
        service.cancel_mission()
    except Exception as exc:
        runtime._fault_run(f"runtime_exception:{type(exc).__name__}:{exc}")
    finally:
        service.shutdown()
    return service.get_status()
