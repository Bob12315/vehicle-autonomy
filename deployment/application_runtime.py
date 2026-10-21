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
from applications.cuadc.catalog import NAMES as BUSINESS_NAMES, build as build_business
from applications.cuadc.actions import register_targets
from contracts.effects.payload import PayloadEffectEnvelope
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


from application.simulation_designs import SimulationDesignSupport


class ApplicationRuntime(SimulationDesignSupport):
    def __init__(self, profile, *, profile_name: str, allow_send=False, runtime=None, event_sink=None, sensor_config=None, vision_config=None, sim_payload=False, mapping_config=None, navigation_config=None, environment_config=None, scenario_scene=None):
        if scenario_scene is not None and (profile.kind!='rover' or profile.vehicle_id!='simulation-rover'):
            raise ValueError('scenario maneuvers require the qualified target_rover front-axle profile')
        self.profile = profile
        self.profile_name = profile_name
        self.allow_send = allow_send
        self.navigation = None
        self.navigation_goals = None
        self.navigation_task = None
        self.autonomy_recipes = None
        self.autonomy_task = None
        self.design_task = None
        self.designs = {}
        if navigation_config is not None:
            if profile.kind != "rover" or mapping_config is None:
                raise ValueError("path following requires explicit Rover simulation and ROS 2 mapping")
            from .navigation import NavigationConfig, NavigationSupervisor
            self.navigation = NavigationSupervisor(NavigationConfig.load(navigation_config), profile.safety,
                lambda event, **fields: self._emit(event, **fields))
            from guidance.navigation_model import DEPLOYMENT_PROFILES
            if profile.vehicle_id!=DEPLOYMENT_PROFILES[self.navigation.config.model.model_id]:
                raise ValueError('navigation model and explicit deployment profile do not match')
            if self.navigation.config.goals_path is not None:
                from application.navigation_goals import GoalCatalog
                self.navigation_goals = GoalCatalog(self.navigation.config.goals_path)
            if self.navigation.config.recipes_path is not None:
                from application.autonomy_recipes import RecipeCatalog
                self.autonomy_recipes=RecipeCatalog(self.navigation.config.recipes_path,self.navigation_goals)
        translator = (ArduRoverCommandTranslator if profile.kind == "rover" else ArduPilotCommandTranslator)
        self.vehicle = runtime or SimulationRuntime(profile, translator=translator(mode_ids=profile.mode_ids),
                                                    event_sink=event_sink)
        if self.navigation is not None:
            self.vehicle.motion_guard = self.navigation.write_guard
        self.environment_path = Path(environment_config) if environment_config else Path(__file__).resolve().parents[1] / f"simulation/environments/{profile.kind}.toml"
        self._environment_source = Environment.load(self.environment_path).check_safety(profile.safety)
        self.scenario_scene = None
        self.scenario_guard = None
        if scenario_scene is not None:
            if profile.kind!='rover':raise ValueError('finite scenario maneuvers require Rover simulation')
            from application.scenario_planning import StaticScene
            from deployment.scenario_guard import ScenarioGuard
            self.scenario_scene=StaticScene(scenario_scene,self._environment_source)
            self.scenario_guard=ScenarioGuard(self.scenario_scene,self._environment_source,getattr(self.vehicle,'motion_guard',None))
            self.vehicle.motion_guard=self.scenario_guard
        self.environment = None
        self.environment_fault = False
        self.events = event_sink or (lambda event: None)
        self.registry = ActionRegistry()
        self.registry.register_typed(SITL_MODE_SPEC, SitlModeAction())
        register_basic(self.registry)
        if self.scenario_scene is not None:
            from actions.rover_maneuver import SPEC,ManeuverAction
            self.registry.register_typed(SPEC,ManeuverAction())
        register_targets(self.registry)
        if self.navigation is not None:
            from actions.path_following import SPEC, FollowPathAction
            self.registry.register_typed(SPEC, FollowPathAction(self.navigation.reader))
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
        self.shutdown_error = None
        self.stops = {}
        self._active_action = None
        self.connected_at_ns = None
        self.task_environment = None
        self.task_name = None
        self.task_configuration_sha256 = None
        if sensor_config and vision_config:raise ValueError('select exactly one observation input')
        self.vision_config = None if vision_config is None else Path(vision_config)
        self.payload = None
        self.payload_port = None
        if sim_payload:
            if profile.kind!='copter':raise ValueError('simulation payload requires Copter')
            from core.payload_execution import PayloadExecution,PayloadSafetyPolicy
            from infrastructure.simulation.payload import SimPayloadPort
            self.payload_port=SimPayloadPort()
            self.payload=PayloadExecution(self.vehicle.authority,self.payload_port,
                PayloadSafetyPolicy(('sim.objects:','vision.recorded:'),max_vehicle_age_ns=profile.safety.max_snapshot_age_ns),self.vehicle.world_reader())
        self.sensor_calibration = None
        self.sensor = None
        self.sensor_epoch = None
        self.mapping = None
        self.slam_candidate = None
        if mapping_config is not None:
            from mapping.exchange import MappingConfig, MappingInput
            if profile.kind != "rover":
                raise ValueError("ROS 2 mapping is currently audited only for the Rover simulation")
            self.mapping = MappingInput(MappingConfig.load(mapping_config, profile.clock_domain_id))
            from localization.slam_candidate import SlamCandidateAudit
            self.slam_candidate = SlamCandidateAudit()
            if self.navigation is not None:self.navigation.source_store = self.mapping.store
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
            if self.design_task and self.design_task.active:
                self.design_task.cancel(self,"design_connection_lost")
                self.design_task.tick(self)
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
                self._cancel_payload()
                self.stops = self.vehicle.end_run()
        if self.environment_fault:
            self.environment = None
            self.vehicle.set_environment(None)
        else:
            if self.environment is None or self.environment.frame_epoch != self.vehicle.world_epoch:
                self.environment = self._environment_source.bind(self.vehicle.world_epoch)
            self.vehicle.set_environment(self.environment.reference)
        if self.sensor_calibration is not None or self.vision_config is not None:
            if self.sensor_epoch != self.vehicle.world_epoch:
                if self.sensor is not None:self.sensor.close()
                if self.vision_config is not None:
                    from sensors.camera.recorded import RecordedVisionSource
                    self.sensor=RecordedVisionSource(self.vision_config,self.vehicle.clock().clock_domain_id)
                else:
                    from sensors.simulation.objects import GazeboObjectSource
                    self.sensor = GazeboObjectSource(self.sensor_calibration,self.vehicle.clock().clock_domain_id)
                self.sensor_epoch = self.vehicle.world_epoch
            for observation in self.sensor.poll(self.vehicle.clock()):
                self.vehicle.ingest_observation(observation)
                self._emit('object_observation',producer=str(observation.producer_id),sequence=observation.sequence,
                    capture_ns=observation.captured_at.monotonic_ns,receive_ns=observation.received_at.monotonic_ns,
                    quality=observation.quality.value,frame=str(observation.frame_id),object_id=str(observation.data.object_id))
        if self.payload is not None:
            for observation in self.payload_port.poll(self.vehicle.clock()):self.vehicle.ingest_observation(observation)
        if self.mapping is not None:
            mapped = self.mapping.poll(self.vehicle.clock(), self.vehicle.world_epoch)
            self.vehicle.set_map(None if mapped is None else mapped.reference,
                                 None if mapped is None else mapped.captured_at)
            if self.navigation is not None:
                self.navigation.update_map(mapped, self.mapping.health, self.vehicle.clock(), self.vehicle.world_epoch)
            if self.slam_candidate is not None:
                from planning.models import MapContext
                context=None if mapped is None else MapContext(mapped.reference,mapped.sha256,self.vehicle.world_epoch,
                    mapped.grid,'live_map',mapped.captured_at,2_500_000_000)
                self.slam_candidate.update(context,self.mapping.health,self.vehicle.clock(),self.vehicle.world_epoch)
        result = self.vehicle.cycle()
        if self.payload is not None:self.payload.tick(self.vehicle.clock())
        if result.fault:
            self.error = result.fault
            if self.task and self.task.view().status not in TERMINAL:
                self.task.abort(result.fault)
                self._cancel_payload()
                self.stops = self.vehicle.end_run()
                if self.scenario_guard is not None:self.scenario_guard.parameters=None
                if self.navigation is not None:self.navigation.finish()
                self._emit("task_failed", error=result.fault)
            self.state = "DEGRADED"
            if self.navigation_task and self.navigation_task.active:
                self.navigation_task.fail(self,result.fault)
                self.navigation_task.tick(self)
            if self.autonomy_task and self.autonomy_task.active:
                self.autonomy_task.cancel(self,result.fault)
                self.autonomy_task.tick(self)
            if self.design_task and self.design_task.active:self.design_task.tick(self)
            return
        self.state = ("DEGRADED" if self.environment_fault else
                      "READY" if result.vehicle_fresh else "CONNECTING")
        if self.task and self.task.view().status not in TERMINAL:
            self.state = "RUNNING_TASK"
            self._advance()
        if self.navigation_task and self.navigation_task.active:
            self.navigation_task.tick(self)
            if self.navigation_task.active and self.navigation_task.status != "RUNNING":
                self.state = self.navigation_task.status
        if self.autonomy_task and self.autonomy_task.active:self.autonomy_task.tick(self)
        if self.design_task and self.design_task.active:self.design_task.tick(self)

    def _advance(self):
        now = self.vehicle.clock()
        world = self.vehicle.world_snapshot()
        if self.task_environment is not None and (world is None or world.environment != self.task_environment
                or world.localization is None or world.vehicle is None):
            self.task.abort("mission_environment_or_localization_unavailable")
        elif (self.navigation is not None and self.navigation.parameters is not None
              and self.navigation.view.error and self.task.view().step_id != "follow_path"):
            self.task.abort(self.navigation.view.error)
        elif now.monotonic_ns - self.task_started_ns > self.task_timeout_ns:
            self.task.abort("mission_deadline_exceeded")
        else:
            for effect_id, envelope in self.envelopes.items():
                status = self._effect_status(effect_id)
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
                if isinstance(envelope,PayloadEffectEnvelope):
                    if self.payload is None:raise RuntimeError('payload port unavailable after preflight')
                    self.payload.dispatch(envelope,self.vehicle.clock())
                else:self.vehicle.dispatch_envelope(envelope)
        if self.task.view().status in TERMINAL:
            self._cancel_payload()
            self.stops = self.vehicle.end_run()
            if self.scenario_guard is not None:self.scenario_guard.parameters=None
            if self.navigation is not None:self.navigation.finish()
            self.state = "READY" if self.vehicle.connected else "DEGRADED"
            self._emit("task_finished", **self._mission_status())

    def _cancel_payload(self):
        if self.payload is not None and self.task is not None:self.payload.cancel(self.task.view().run_id)

    def _effect_status(self,key):
        if isinstance(self.envelopes.get(key),PayloadEffectEnvelope):return None if self.payload is None else self.payload.status(key)
        return self.vehicle.effect_status(key)

    def task_status(self):
        if self.autonomy_task is not None:return self.autonomy_task.view(self)
        if self.navigation_task is not None:
            return self.navigation_task.view(self)
        return self._mission_status()

    def _mission_status(self):
        if self.task is None:
            return None
        view = self.task.view()
        return {"task_id": str(view.run_id), "mission": self.task_name, "configuration_sha256":self.task_configuration_sha256, "status": view.status.value, "step": view.step_id,
                "error": view.error, "steps": [{"step": r.step_id, "reason": r.reason.value,
                    "error": r.error} for r in view.results],
                "effects": {key: self._effect_status(key) for key in self.envelopes},
                "requests": {key: {"action_id": str(envelope.action_instance_id),
                    "effect_type": type(envelope.effect).__name__, "created_ns": envelope.created_at.monotonic_ns,
                    "deadline_ns": envelope.deadline.monotonic_ns} for key,envelope in self.envelopes.items()},
                "stops": self.stops}

    def map_view(self):
        world = self.vehicle.world_snapshot()
        if self.mapping is None or world is None or world.map is None or not self.mapping.health.get('valid'):
            raise ValueError('fresh adopted map required')
        # Public read-only export. Loading a saved preview never sets WorldSnapshot.map.
        grid = self.mapping.store.load(self.mapping.health['sha256'])
        path=[]
        if self.navigation is not None and self.navigation.parameters is not None and self.navigation.binding is not None:
            path=[[point.x,point.y] for point in (self.navigation.binding.to_map(p) for p in self.navigation.parameters.poses)]
        return {'grid': grid.document(), 'metadata': dict(self.mapping.health), 'path_frame':'map',
                'path':path, 'control_eligible': False}

    def get_status(self, *, include_task=True):
        world = self.vehicle.world_snapshot()
        now = self.vehicle.clock()
        state = world.vehicle if world else None
        pose = state.reported_pose if state else None
        origin_error='vehicle/environment unavailable'
        if self.environment is not None and state is not None:
            try:self.environment.validate_origin(state);origin_error=None
            except ValueError as exc:origin_error=str(exc)
        twist = state.reported_twist if state else None
        return {"profile": self.profile_name, "vehicle_kind": self.profile.kind,
                "missions": sorted(set(self.plans) | set(MISSION_NAMES) |
                    ({'follow_path'} if self.navigation is not None else set()) |
                    ({'navigate:'+name for name in self.navigation_goals.goals} if self.navigation_goals is not None else set())),
                "clock_domain_id": str(now.clock_domain_id),
                "state": self.state, "started_at": self.started_at, "session_id": self.vehicle.session_id,
                "connected": self.vehicle.connected, "error": self.error,"shutdown_error":self.shutdown_error,
                "world_version": None if world is None else {"generation": world.version.generation_id,
                    "revision": world.version.revision},
                "motion_warmup_remaining_ns":None if self.connected_at_ns is None else max(0,self.profile.warmup_ns-(now.monotonic_ns-self.connected_at_ns)),
                "world_age_ns": None if world is None else now.elapsed_ns_since(world.published_at),
                "vehicle": None if state is None else {"quality": state.health.quality.value,
                    "armed": state.operation.armed, "mode": state.operation.native_mode,
                    "pose": None if pose is None else {"frame": str(pose.frame_id),
                        "position": [pose.value.position.x, pose.value.position.y, pose.value.position.z],
                        "orientation_xyzw": [pose.value.orientation.x, pose.value.orientation.y,
                                             pose.value.orientation.z, pose.value.orientation.w],
                        "captured_ns": pose.captured_at.monotonic_ns,
                        "age_ns": now.elapsed_ns_since(pose.captured_at)}},
                "twist": None if twist is None else {"frame": str(twist.frame_id),
                    "linear": [twist.value.linear.x, twist.value.linear.y, twist.value.linear.z],
                    "angular": [twist.value.angular.x, twist.value.angular.y, twist.value.angular.z],
                    "captured_ns": twist.captured_at.monotonic_ns},
                "environment": None if self.environment is None else {
                    "id": self.environment.resource_id, "generation": self.environment.version.generation_id,
                    "revision": self.environment.version.revision, "frame": str(self.environment.frame),
                    "home": self.environment.home_name, "home_source": self.environment.home_source,
                    "origin_source": self.environment.origin_source,"origin_verified":origin_error is None,"origin_error":origin_error, "points": [p.name for p in self.environment.points],
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
                "sensor": None if self.sensor is None else (dict(self.sensor.health) if self.vision_config is not None else {"kind":"sim_objects","source":self.sensor_calibration.source,
                    "version":self.sensor_calibration.version,"error":self.sensor.projector.error}),
                "payload":None if self.payload_port is None else self.payload_port.inventory(),
                "mapping": None if self.mapping is None else {**self.mapping.health,
                    "adopted": bool(world is not None and world.map is not None)},
                "scenario": None if self.scenario_scene is None else {"static_scene_sha256":self.scenario_scene.sha256,"kind":"known_static_scene","live_obstacle_avoidance":False},
                "navigation": None if self.navigation is None else self.navigation.status(world, now),
                "slam_localization_candidate":None if self.slam_candidate is None else self.slam_candidate.view(now),
                "system_send": self.vehicle.authority.system_send,
                "action_send": self.vehicle.authority.action_send, "task": (self.design_task.view(self) if self.design_task is not None else self.task_status()) if include_task else None}

    def start_mission(self, name, *, _navigation_child=False, _design_child=False, _scenario=None):
        scenario_mission=_scenario is not None
        if scenario_mission and (not _design_child or self.design_task is None or not self.design_task.active
                or self.design_task.prepared.get(self.design_task.index) is not _scenario
                or name!=f'scenario:{self.design_task.design.sha256}:{self.design_task.index}'):
            raise ValueError('only the active admitted design can start its bound maneuver')
        if not _navigation_child and not _design_child:
            if self.design_task and self.design_task.active:
                raise ValueError('another designed task is active')
            self.design_task=None
        if not _navigation_child:
            if self.autonomy_task and self.autonomy_task.active:
                raise ValueError('another autonomy business task is active')
            if self.navigation_task and self.navigation_task.active:
                raise ValueError("another navigation task is active")
            self.autonomy_task=None
            if name.startswith('autonomy:'):
                if self.autonomy_recipes is None:raise ValueError('autonomy recipes are not configured')
                world=self.vehicle.world_snapshot()
                if (not self.allow_send or self.stopping or self.state!='READY' or self.environment is None
                        or world is None or world.vehicle is None or world.localization is None
                        or world.environment!=self.environment.reference or world.vehicle.operation.armed):
                    raise ValueError('autonomy business requires authorized fresh disarmed mapped READY application')
                from deployment.autonomy_business import AutonomyBusiness
                self.autonomy_task=AutonomyBusiness(self,name[len('autonomy:'):])
                self._emit('autonomy_business_started',task_id=self.autonomy_task.task_id,recipe=name)
                return self.task_status()
            if name.startswith("navigate:"):
                return self._start_navigation(name[len("navigate:"):])
            self.navigation_task = None
        navigation_mission = name == "follow_path" and self.navigation is not None
        if name not in self.plans and name not in MISSION_NAMES and name not in BUSINESS_NAMES and not navigation_mission and not scenario_mission:
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
        if name in MISSION_NAMES or name in BUSINESS_NAMES or navigation_mission or scenario_mission:
            if self.environment is None or world.environment != self.environment.reference or world.localization is None:
                raise ValueError("bound environment and fresh localization required")
            if name != "safe_recovery" and (self.connected_at_ns is None or self.vehicle.clock().monotonic_ns-self.connected_at_ns < self.profile.warmup_ns):
                raise ValueError("simulation motion warmup incomplete")
            self.environment.validate_origin(world.vehicle)
            if scenario_mission:
                if self.scenario_guard is None:raise ValueError('scenario composition required')
                from application.scenario_planning import build as build_scenario
                plan=build_scenario(_scenario,self.profile.mode_ids['GUIDED'])
                self.scenario_guard.parameters=_scenario
            elif navigation_mission:
                from applications.navigation import build as build_navigation
                parameters = self.navigation.admit(world, self.vehicle.clock())
                plan = build_navigation(parameters, self.profile.mode_ids["GUIDED"])
            elif name in BUSINESS_NAMES:
                if self.sensor is None:raise ValueError('business mission requires explicit observation input')
                plan=build_business(name,self.profile.kind,self.environment,self.profile.mode_ids['GUIDED'],self.payload is not None)
                if name=='cuadc_demo' and 'sim_payload_1' not in self.payload_port.loaded:raise ValueError('simulation payload already consumed; no automatic reset')
            else:plan = build(name, self.profile.kind, self.environment, self.profile.mode_ids["GUIDED"])
            self.task_environment = self.environment.reference
        else:
            plan = self.plans[name]
            self.task_environment = None
        try:
            compiled = MissionValidator(self.registry).compile(plan, VehicleCapabilities(capabilities(self.profile.kind) | (frozenset({"payload_release"}) if self.payload is not None else frozenset())))
            self.task_configuration_sha256=hashlib.sha256(repr(tuple(step.step for step in compiled.steps)).encode()).hexdigest()
            run_id = f"application:{uuid4().hex}"
            action_id = f"{run_id}:{compiled.steps[0].step.step_id}:1"
            self.vehicle.begin_run(allow_send=True, run_id=run_id, action_id=action_id)
        except (ValueError, TypeError, RuntimeError):
            if scenario_mission:self.scenario_guard.parameters=None
            if navigation_mission:self.navigation.finish()
            raise
        if navigation_mission:self.navigation.consume()
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
        return self._mission_status()

    def _start_navigation(self, name):
        if self.navigation_goals is None:
            raise ValueError("navigation goal catalog is not configured")
        if not self.allow_send or self.stopping or self.state != "READY":
            raise ValueError("navigation requires an explicitly authorized idle READY application")
        if self.task and self.task.view().status not in TERMINAL:
            raise ValueError("another mission is active")
        world = self.vehicle.world_snapshot()
        if (world is None or world.vehicle is None or world.vehicle.operation.armed
                or self.environment is None or world.environment != self.environment.reference
                or self.navigation.context is None or world.map != self.navigation.context.reference):
            raise ValueError("fresh disarmed vehicle, environment and adopted map required")
        if self.connected_at_ns is None or self.vehicle.clock().monotonic_ns-self.connected_at_ns < self.profile.warmup_ns:
            raise ValueError("simulation motion warmup incomplete")
        self.environment.validate_origin(world.vehicle)
        from .goal_navigation import GoalNavigation
        self.navigation_task = GoalNavigation(self,name)
        self.state = "PLANNING"
        return self.navigation_task.view(self)

    def _launch_goal(self,name):
        self._start_navigation(name)
        return self.navigation_task

    def export_map_anchor(self,path):
        from mapping.anchors import MapAnchor
        path=Path(path)
        if not path.is_absolute() or self.state!='READY' or self.navigation is None or self.navigation.context is None:
            raise ValueError('map anchor registration requires explicit path and idle mapped READY application')
        if (self.navigation_task and self.navigation_task.active) or (self.autonomy_task and self.autonomy_task.active):
            raise ValueError('map registration during navigation is forbidden')
        world=self.vehicle.world_snapshot()
        if (world is None or world.vehicle is None or world.environment!=self.environment.reference
                or world.map!=self.navigation.context.reference):
            raise ValueError('map registration requires an adopted WorldSnapshot')
        anchor=MapAnchor.create(self.environment,self.navigation.context,self.navigation.binding,self.vehicle.clock(),world.vehicle,
            system_send=self.vehicle.authority.system_send,action_send=self.vehicle.authority.action_send)
        anchor.save(path)
        self._emit('map_anchor_registered',path=str(path),**anchor.document())
        return anchor.document()

    def cancel_mission(self, *, _design_child=False):
        if not _design_child and self.design_task and self.design_task.active:
            self.design_task.cancel(self)
            return self.design_task.view(self)
        if self.autonomy_task and self.autonomy_task.active:
            self.autonomy_task.cancel(self)
            return self.task_status()
        if self.navigation_task and self.navigation_task.active:
            self.navigation_task.cancel(self)
            return self.task_status()
        return self._cancel_child()

    def _cancel_child(self):
        if self.task is None or self.task.view().status in TERMINAL:
            raise ValueError("no active mission")
        self._cancel_payload()
        self.vehicle.cancel_pending_requests()
        self.task.cancel()
        return self.task_status()

    def request_shutdown(self):
        if self.design_task and self.design_task.active:self.design_task.cancel(self)
        if self.autonomy_task and self.autonomy_task.active:self.autonomy_task.cancel(self)
        if self.navigation_task and self.navigation_task.active:
            self.navigation_task.cancel(self)
        self.stopping = True
        self.state = "STOPPING"
        return {"state": self.state}

    def shutdown(self):
        self.request_shutdown()
        self._cancel_payload()
        self.vehicle.cancel_pending_requests()
        if self.task and self.task.view().status not in TERMINAL:
            self.task.cancel()
            self.task.abort("shutdown; sent commands cannot be undone")
        try:
            self.stops.update(self.vehicle.shutdown())
        finally:
            if self.navigation is not None:self.navigation.finish()
            if self.navigation_task is not None:
                try:self.navigation_task.close(self)
                except RuntimeError as exc:self.shutdown_error=str(exc)
            if self.autonomy_task is not None and self.autonomy_task.active:
                self.autonomy_task._finish(self,'CANCELLED','application_shutdown; consult runtime stop evidence')
            sensor,self.sensor=self.sensor,None
            if sensor is not None:
                try:sensor.close()
                except Exception as exc:self.shutdown_error=f'sensor_shutdown_unconfirmed:{type(exc).__name__}'
        if self.design_task and self.design_task.active:
            self.design_task._finish(self,'CANCELLED','application_shutdown; cleanup evidence is unconfirmed')
        self.state = "STOPPED"
        self._emit("application_stopped", stops=self.stops)
        return self.get_status()
