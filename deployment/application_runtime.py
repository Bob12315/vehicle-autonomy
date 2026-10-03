"""Single-threaded localhost application composition around the vehicle runtime."""
from __future__ import annotations

from datetime import datetime, timezone
import time
from uuid import uuid4

from contracts.core.primitives import RunId
from contracts.decision import EffectPhase, EffectResult, MissionPlan, MissionStep
from contracts.vehicle.ports import VehicleCapabilities
from core.action_registry import ActionRegistry
from core.mission import MissionValidator
from core.mission_runtime import MissionRuntime, RunStatus
from core.sitl_mode_action import SITL_MODE_SPEC, SitlModeAction, SitlModeParameters
from vehicles.multirotor.ardupilot_commands import ArduPilotCommandTranslator
from vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator
from .simulation_runtime import SimulationRuntime

TERMINAL = (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED)


class ApplicationRuntime:
    def __init__(self, profile, *, profile_name: str, allow_send=False, runtime=None, event_sink=None):
        self.profile = profile
        self.profile_name = profile_name
        self.allow_send = allow_send
        translator = (ArduRoverCommandTranslator if profile.kind == "rover" else ArduPilotCommandTranslator)
        self.vehicle = runtime or SimulationRuntime(profile, translator=translator(mode_ids=profile.mode_ids),
                                                    event_sink=event_sink)
        self.events = event_sink or (lambda event: None)
        self.registry = ActionRegistry()
        self.registry.register_typed(SITL_MODE_SPEC, SitlModeAction())
        mode = "HOLD" if profile.kind == "rover" else "GUIDED"
        self.plans = {"disarmed_mode": MissionPlan("disarmed_mode", (
            MissionStep("mode", SITL_MODE_SPEC.name, SitlModeParameters(mode, profile.mode_ids[mode])),))}
        self.state = "STARTING"
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.error = None
        self.task = None
        self.envelopes = {}
        self.task_started_ns = 0
        self.task_timeout_ns = 15_000_000_000
        self.retry_at_ns = 0
        self.retry_delay_ns = 200_000_000
        self.stopping = False
        self.stops = {}
        self._active_action = None

    def _emit(self, event, **fields):
        self.events({"event": event, "profile": self.profile_name, **fields})

    def cycle(self):
        if self.stopping:
            return
        now = self.vehicle.clock()
        if not self.vehicle.connected:
            self.state = "CONNECTING"
            if now.monotonic_ns < self.retry_at_ns:
                return
            try:
                self.vehicle.connect()
                self.error = None
                self.retry_delay_ns = 200_000_000
            except (OSError, ConnectionError) as exc:
                self.error = f"connect:{type(exc).__name__}"
                self.retry_at_ns = now.monotonic_ns + self.retry_delay_ns
                self.retry_delay_ns = min(2_000_000_000, self.retry_delay_ns * 2)
                return
        result = self.vehicle.cycle()
        if result.fault:
            self.error = result.fault
            if self.task and self.task.view().status not in TERMINAL:
                self.task.abort(result.fault)
                self._emit("task_failed", error=result.fault)
            self.state = "DEGRADED"
            return
        self.state = "READY" if result.vehicle_fresh else "CONNECTING"
        if self.task and self.task.view().status not in TERMINAL:
            self.state = "RUNNING_TASK"
            self._advance()

    def _advance(self):
        now = self.vehicle.clock()
        if now.monotonic_ns - self.task_started_ns > self.task_timeout_ns:
            self.task.abort("mission_deadline_exceeded")
        else:
            for effect_id, envelope in self.envelopes.items():
                status = self.vehicle.effect_status(effect_id)
                if status:
                    self.task.record_effect_result(EffectResult(effect_id, str(envelope.action_instance_id),
                        EffectPhase(status["phase"]), status["command_id"], self.vehicle.session_id, status["reason"]))
            update = self.task.view()
            action_id = f"{update.run_id}:{update.step_id}:{max(1, update.attempt)}"
            if action_id != self._active_action:
                self.vehicle.authorize_action(action_id, allow_send=self.allow_send)
                self._active_action = action_id
            update = self.task.tick(now)
            for envelope in update.effects:
                self.envelopes[str(envelope.effect_id)] = envelope
                self.vehicle.dispatch_envelope(envelope)
        if self.task.view().status in TERMINAL:
            self.stops = self.vehicle.end_run()
            self.state = "READY" if self.vehicle.connected else "DEGRADED"
            self._emit("task_finished", **self.task_status())

    def task_status(self):
        if self.task is None:
            return None
        view = self.task.view()
        return {"task_id": str(view.run_id), "status": view.status.value, "step": view.step_id,
                "error": view.error, "steps": [{"step": r.step_id, "reason": r.reason.value,
                    "error": r.error} for r in view.results],
                "effects": {key: self.vehicle.effect_status(key) for key in self.envelopes},
                "stops": self.stops}

    def get_status(self):
        world = self.vehicle.world_snapshot()
        now = self.vehicle.clock()
        state = world.vehicle if world else None
        pose = state.reported_pose if state else None
        return {"profile": self.profile_name, "vehicle_kind": self.profile.kind,
                "state": self.state, "started_at": self.started_at, "session_id": self.vehicle.session_id,
                "connected": self.vehicle.connected, "error": self.error,
                "world_version": None if world is None else {"generation": world.version.generation_id,
                    "revision": world.version.revision},
                "world_age_ns": None if world is None else now.elapsed_ns_since(world.published_at),
                "vehicle": None if state is None else {"quality": state.health.quality.value,
                    "armed": state.operation.armed, "mode": state.operation.native_mode,
                    "pose": None if pose is None else {"frame": str(pose.frame_id),
                        "position": [pose.value.position.x, pose.value.position.y, pose.value.position.z],
                        "age_ns": now.elapsed_ns_since(pose.captured_at)}},
                "system_send": self.vehicle.authority.system_send,
                "action_send": self.vehicle.authority.action_send, "task": self.task_status()}

    def start_mission(self, name):
        if name not in self.plans:
            raise ValueError("mission is not registered")
        if not self.allow_send:
            raise ValueError("application started without --allow-send")
        if self.stopping or self.state != "READY":
            raise ValueError("fresh idle application required")
        if self.task and self.task.view().status not in TERMINAL:
            raise ValueError("another mission is active")
        world = self.vehicle.world_snapshot()
        if world is None or world.vehicle is None or world.vehicle.operation.armed:
            raise ValueError("fresh disarmed vehicle required")
        compiled = MissionValidator(self.registry).compile(self.plans[name], VehicleCapabilities(frozenset()))
        run_id = f"application:{uuid4().hex}"
        action_id = f"{run_id}:{compiled.steps[0].step.step_id}:1"
        self.vehicle.begin_run(allow_send=True, run_id=run_id, action_id=action_id)
        self.task = MissionRuntime(compiled, self.vehicle, RunId(run_id),
                                   max_snapshot_age_ns=self.profile.safety.max_snapshot_age_ns)
        self.envelopes = {}
        self.stops = {}
        self._active_action = action_id
        self.task_started_ns = self.vehicle.clock().monotonic_ns
        self.state = "RUNNING_TASK"
        self._emit("task_started", mission=name, task_id=run_id)
        return self.task_status()

    def cancel_mission(self):
        if self.task is None or self.task.view().status in TERMINAL:
            raise ValueError("no active mission")
        self.task.cancel()
        return self.task_status()

    def request_shutdown(self):
        self.stopping = True
        self.state = "STOPPING"
        return {"state": self.state}

    def shutdown(self):
        self.request_shutdown()
        if self.task and self.task.view().status not in TERMINAL:
            self.task.cancel()
            self.task.abort("shutdown; sent commands cannot be undone")
        self.stops = self.vehicle.shutdown()
        self.state = "STOPPED"
        self._emit("application_stopped", stops=self.stops)
        return self.get_status()
