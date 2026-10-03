"""Single-threaded localhost application composition around the vehicle runtime."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
from environments.resources import Environment
import time
from uuid import uuid4

from contracts.core.primitives import RunId
from actions.basic import register_basic
from applications.basic_catalog import MISSION_NAMES, build, capabilities
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
    def __init__(self, profile, *, profile_name: str, allow_send=False, runtime=None, event_sink=None, sensor_config=None):
        self.profile = profile
        self.profile_name = profile_name
        self.allow_send = allow_send
        translator = (ArduRoverCommandTranslator if profile.kind == "rover" else ArduPilotCommandTranslator)
        self.vehicle = runtime or SimulationRuntime(profile, translator=translator(mode_ids=profile.mode_ids),
                                                    event_sink=event_sink)
        self.environment_path = Path(__file__).resolve().parents[1] / f"simulation/environments/{profile.kind}.toml"
        self._environment_source = Environment.load(self.environment_path).check_safety(profile.safety)
        self.environment = None
        self.environment_fault = False
        self.events = event_sink or (lambda event: None)
        self.registry = ActionRegistry()
        self.registry.register_typed(SITL_MODE_SPEC, SitlModeAction())
        register_basic(self.registry)
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
        self.connected_at_ns = None
        self.task_environment = None
        self.task_name = None
        self.sensor_calibration = None
        self.sensor = None
        self.sensor_epoch = None
        if sensor_config is not None:
            from sensors.simulation.objects import ObjectCalibration
            self.sensor_calibration = ObjectCalibration.load(Path(sensor_config))

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
                self.connected_at_ns = self.vehicle.clock().monotonic_ns
                self.error = None
                self.retry_delay_ns = 200_000_000
            except (OSError, ConnectionError) as exc:
                self.error = f"connect:{type(exc).__name__}"
                self.retry_at_ns = now.monotonic_ns + self.retry_delay_ns
                self.retry_delay_ns = min(2_000_000_000, self.retry_delay_ns * 2)
                return
        if hashlib.sha256(self.environment_path.read_bytes()).hexdigest() != self._environment_source.content_hash:
            self.environment_fault = True
            self.error = "environment_configuration_changed; restart and preflight required"
            if self.task and self.task.view().status not in TERMINAL:
                self.task.abort(self.error)
                self.stops = self.vehicle.end_run()
        if self.environment_fault:
            self.environment = None
            self.vehicle.set_environment(None)
        else:
            if self.environment is None or self.environment.frame_epoch != self.vehicle.world_epoch:
                self.environment = self._environment_source.bind(self.vehicle.world_epoch)
            self.vehicle.set_environment(self.environment.reference)
        if self.sensor_calibration is not None:
            if self.sensor_epoch != self.vehicle.world_epoch:
                if self.sensor is not None:self.sensor.close()
                from sensors.simulation.objects import GazeboObjectSource
                self.sensor = GazeboObjectSource(self.sensor_calibration,self.vehicle.clock().clock_domain_id)
                self.sensor_epoch = self.vehicle.world_epoch
            for observation in self.sensor.poll(self.vehicle.clock()):
                self.vehicle.ingest_observation(observation)
                self._emit('object_observation',producer=str(observation.producer_id),sequence=observation.sequence,
                    capture_ns=observation.captured_at.monotonic_ns,receive_ns=observation.received_at.monotonic_ns,
                    quality=observation.quality.value,frame=str(observation.frame_id),object_id=str(observation.data.object_id))
        result = self.vehicle.cycle()
        if result.fault:
            self.error = result.fault
            if self.task and self.task.view().status not in TERMINAL:
                self.task.abort(result.fault)
                self.stops = self.vehicle.end_run()
                self._emit("task_failed", error=result.fault)
            self.state = "DEGRADED"
            return
        self.state = ("DEGRADED" if self.environment_fault else
                      "READY" if result.vehicle_fresh else "CONNECTING")
        if self.task and self.task.view().status not in TERMINAL:
            self.state = "RUNNING_TASK"
            self._advance()

    def _advance(self):
        now = self.vehicle.clock()
        world = self.vehicle.world_snapshot()
        if self.task_environment is not None and (world is None or world.environment != self.task_environment
                or world.localization is None or world.vehicle is None):
            self.task.abort("mission_environment_or_localization_unavailable")
        elif now.monotonic_ns - self.task_started_ns > self.task_timeout_ns:
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
            if update.error:
                self.task.abort(update.error)
            for envelope in update.effects:
                self._emit("effect_requested", run_id=str(envelope.run_id), action_id=str(envelope.action_instance_id),
                           effect_id=str(envelope.effect_id), effect_type=type(envelope.effect).__name__)
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
        return {"task_id": str(view.run_id), "mission": self.task_name, "status": view.status.value, "step": view.step_id,
                "error": view.error, "steps": [{"step": r.step_id, "reason": r.reason.value,
                    "error": r.error} for r in view.results],
                "effects": {key: self.vehicle.effect_status(key) for key in self.envelopes},
                "requests": {key: {"action_id": str(envelope.action_instance_id),
                    "effect_type": type(envelope.effect).__name__, "created_ns": envelope.created_at.monotonic_ns,
                    "deadline_ns": envelope.deadline.monotonic_ns} for key,envelope in self.envelopes.items()},
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
                "environment": None if self.environment is None else {
                    "id": self.environment.resource_id, "generation": self.environment.version.generation_id,
                    "revision": self.environment.version.revision, "frame": str(self.environment.frame),
                    "home": self.environment.home_name, "home_source": self.environment.home_source,
                    "origin_source": self.environment.origin_source, "points": [p.name for p in self.environment.points],
                    "regions": [r.name for r in self.environment.regions]},
                "localization": None if world is None or world.localization is None else {
                    "quality": world.localization.quality.value, "source": str(world.localization.producer_id),
                    "frame": str(world.localization.pose.frame_id),
                    "age_ns": now.elapsed_ns_since(world.localization.pose.captured_at),
                    "source_revision": world.localization.version.revision,
                    "transform_epoch": self.vehicle.localization.epoch,
                    "position": [world.localization.pose.value.position.x, world.localization.pose.value.position.y,
                                 world.localization.pose.value.position.z]},
                "objects": [] if world is None else [{"id":str(obj.object_id),"label":obj.label,
                    "producer":str(obj.producer_id),"observation":str(obj.source_observation_id),"frame":str(obj.position.frame_id),
                    "age_ns":now.elapsed_ns_since(obj.position.captured_at),"quality":obj.quality.value,
                    "confidence":obj.confidence,"position":[obj.position.value.x,obj.position.value.y,obj.position.value.z]} for obj in world.objects],
                "sensor": None if self.sensor is None else {"kind":"sim_objects","source":self.sensor_calibration.source,
                    "version":self.sensor_calibration.version,"error":self.sensor.projector.error},
                "system_send": self.vehicle.authority.system_send,
                "action_send": self.vehicle.authority.action_send, "task": self.task_status()}

    def start_mission(self, name):
        if name not in self.plans and name not in MISSION_NAMES:
            raise ValueError("mission is not registered")
        if not self.allow_send:
            raise ValueError("application started without --allow-send")
        if self.stopping or self.state != "READY":
            raise ValueError("fresh idle application required")
        if self.task and self.task.view().status not in TERMINAL:
            raise ValueError("another mission is active")
        world = self.vehicle.world_snapshot()
        if world is None or world.vehicle is None or (name != "safe_recovery" and world.vehicle.operation.armed):
            raise ValueError("fresh disarmed vehicle required")
        if name in MISSION_NAMES:
            if self.environment is None or world.environment != self.environment.reference or world.localization is None:
                raise ValueError("bound environment and fresh localization required")
            if name != "safe_recovery" and (self.connected_at_ns is None or self.vehicle.clock().monotonic_ns-self.connected_at_ns < self.profile.warmup_ns):
                raise ValueError("simulation motion warmup incomplete")
            self.environment.validate_origin(world.vehicle)
            plan = build(name, self.profile.kind, self.environment, self.profile.mode_ids["GUIDED"])
            self.task_environment = self.environment.reference
        else:
            plan = self.plans[name]
            self.task_environment = None
        compiled = MissionValidator(self.registry).compile(plan, VehicleCapabilities(capabilities(self.profile.kind)))
        run_id = f"application:{uuid4().hex}"
        action_id = f"{run_id}:{compiled.steps[0].step.step_id}:1"
        self.vehicle.begin_run(allow_send=True, run_id=run_id, action_id=action_id)
        self.task = MissionRuntime(compiled, self.vehicle.world_reader(), RunId(run_id),
                                   max_snapshot_age_ns=self.profile.safety.max_snapshot_age_ns)
        self.envelopes = {}
        self.stops = {}
        self.task_name = name
        self.task_timeout_ns = sum(getattr(step.step.parameters,"timeout_ns",15_000_000_000)+8_000_000_000
                                   for step in compiled.steps)
        self._active_action = action_id
        self.task_started_ns = self.vehicle.clock().monotonic_ns
        self.state = "RUNNING_TASK"
        self._emit("task_started", mission=name, task_id=run_id)
        return self.task_status()

    def cancel_mission(self):
        if self.task is None or self.task.view().status in TERMINAL:
            raise ValueError("no active mission")
        self.vehicle.cancel_pending_requests()
        self.task.cancel()
        return self.task_status()

    def request_shutdown(self):
        self.stopping = True
        self.state = "STOPPING"
        return {"state": self.state}

    def shutdown(self):
        self.request_shutdown()
        self.vehicle.cancel_pending_requests()
        if self.task and self.task.view().status not in TERMINAL:
            self.task.cancel()
            self.task.abort("shutdown; sent commands cannot be undone")
        if self.sensor is not None:self.sensor.close();self.sensor=None
        self.stops.update(self.vehicle.shutdown())
        self.state = "STOPPED"
        self._emit("application_stopped", stops=self.stops)
        return self.get_status()
