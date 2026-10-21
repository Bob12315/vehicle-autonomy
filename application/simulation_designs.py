"""Application-owned simulation design admission, not a motion command port."""
import hashlib
import json
import math
from pathlib import Path

from application.proposals import context_key
from intelligence.designs import MissionDesign


class SimulationDesignSupport:
    def _design_capabilities(self):
        capabilities = {'disarmed_mode':{'description':'Confirm disarmed HOLD (Rover) or GUIDED (Copter). No motion.'},
                        'basic_route':{'description':'Execute the configured finite route, return HOME, stop/land and disarm.'}}
        route=Path(__file__).resolve().parents[1]/f'simulation/missions/{self.profile.kind}.toml'
        capabilities['basic_route']['configuration_sha256']=hashlib.sha256(route.read_bytes()).hexdigest()
        if self.scenario_scene is not None:
            self.scenario_scene.check()
            from application.scenario_planning import catalog
            capabilities.update(catalog(self.environment or self._environment_source))
        if self.navigation_goals is not None:
            self.navigation_goals.check(self.environment)
            for name,goal in self.navigation_goals.goals.items():
                capabilities['navigate:'+name] = {'description':'Navigate to registered '+name+', observe Stop and disarm.',
                                                 'frame':goal.frame}
        if self.autonomy_recipes is not None:
            self.autonomy_recipes.check()
            for name,recipe in self.autonomy_recipes.recipes.items():
                capabilities['autonomy:'+name] = {'description':'Execute registered route/inspection recipe.',
                    'goals':list(recipe.goals), 'inspection':recipe.inspection_label}
        return capabilities

    def design_catalog(self):
        if not self.profile_name.endswith('_sim'):
            raise ValueError('task design execution is restricted to explicit simulation profiles')
        state = self.get_status(include_task=False)
        capabilities = self._design_capabilities()
        context = {'application':context_key(state), 'capabilities':capabilities,
            'environment_config':self._environment_source.content_hash,
            'scenario_scene':None if self.scenario_scene is None else self.scenario_scene.sha256,
            'navigation_config':None if self.navigation is None else self.navigation.config.source_sha256,
            'goal_catalog':None if self.navigation_goals is None else self.navigation_goals.sha256,
            'recipe_catalog':None if self.autonomy_recipes is None else self.autonomy_recipes.sha256,
            'map_source':None if self.navigation is None or self.navigation.context is None else
                str(self.navigation.context.reference.version.generation_id)}
        if self.navigation_goals is not None and self.navigation_goals.anchor_path is not None:
            context['anchor_sha256'] = hashlib.sha256(self.navigation_goals.anchor_path.read_bytes()).hexdigest()
        digest = hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest()
        return {'schema':1, 'context':digest, 'session_id':state['session_id'],
                'context_components':context,
                'capabilities':capabilities, 'max_steps':8, 'max_duration_s':600,
                'simulation_only':True, 'requires_human_approval':True}

    def design_boundary(self):
        world,now = self.vehicle.world_snapshot(),self.vehicle.clock()
        reasons = []
        if not self.vehicle.connected or world is None or world.vehicle is None:
            return {'eligible':False,'reasons':['vehicle_unavailable'],'capture_ns':None}
        if world.vehicle.operation.armed is not False:
            reasons.append('vehicle_not_disarmed')
        if (world.vehicle.health.quality.value != 'VALID'
                or not 0 <= now.elapsed_ns_since(world.vehicle.published_at) <= 500_000_000):
            reasons.append('vehicle_state_not_fresh_valid')
        authority = self.vehicle.authority
        if authority.system_send or authority.action_send or authority.lease is not None:
            reasons.append('previous_authority_not_released')
        loc = world.localization
        if loc is None or loc.twist is None:
            reasons.append('localization_or_twist_missing')
        else:
            if loc.quality.value != 'VALID':
                reasons.append('localization_not_valid')
            if any(not 0 <= now.elapsed_ns_since(v.captured_at) <= 500_000_000 for v in (loc.pose,loc.twist)):
                reasons.append('localization_or_twist_stale')
            twist=loc.twist.value
            if (math.sqrt(twist.linear.x**2+twist.linear.y**2+twist.linear.z**2) > .05
                    or abs(twist.angular.z) > .05):
                reasons.append('vehicle_not_observed_stationary')
        return {'eligible':not reasons, 'reasons':reasons,
                'capture_ns':None if loc is None else loc.pose.captured_at.monotonic_ns}

    def _prepare_scenario(self,design,context,anchor=None):
        from actions.basic import yaw
        from guidance.path_following import drive_reference,angle
        from planning.models import Pose2D
        from application.scenario_planning import resolve
        world=self.vehicle.world_snapshot();now=self.vehicle.clock()
        current=world.localization.pose.value
        pose=drive_reference(Pose2D(current.position.x,current.position.y,yaw(current)))
        if anchor is not None:
            if (type(anchor) is not dict or set(anchor)!={'x','y','yaw','captured_ns','context'}
                    or anchor['context']!=context or type(anchor['captured_ns']) is not int
                    or not 0<=now.monotonic_ns-anchor['captured_ns']<=60_000_000_000
                    or any(type(anchor[k]) not in (int,float) or not math.isfinite(anchor[k]) for k in ('x','y','yaw'))):
                raise ValueError('known fresh preview anchor required')
            start=Pose2D(anchor['x'],anchor['y'],anchor['yaw'])
            if math.hypot(pose.x-start.x,pose.y-start.y)>.1 or abs(angle(pose.yaw-start.yaw))>.1:
                raise ValueError('vehicle moved since preview; design again')
        else:
            start=pose;anchor={'x':pose.x,'y':pose.y,'yaw':pose.yaw,'captured_ns':now.monotonic_ns,'context':context}
        prepared,preview=resolve(design,self.environment,start,self.scenario_scene)
        return prepared,preview,anchor

    def design_preflight(self, document, expected_context, *, anchor=None):
        catalog=self.design_catalog()
        if type(expected_context) is not str or expected_context != catalog['context']:
            raise ValueError('design environment/session/capability context changed; current='+catalog['context'])
        design=MissionDesign.parse(json.dumps(document),catalog['capabilities'])
        if design.decision!='propose':
            raise ValueError('only proposed finite designs can pass preflight')
        reasons=[]
        if not self.allow_send:reasons.append('simulation_SEND_not_authorized')
        if self.stopping or self.state!='READY':reasons.append('application_not_idle_READY')
        if self.design_task is not None and self.design_task.active:reasons.append('another_design_active')
        if ((self.task is not None and self.task.view().status.value not in ('SUCCEEDED','FAILED','CANCELLED'))
                or (self.navigation_task is not None and self.navigation_task.active)
                or (self.autonomy_task is not None and self.autonomy_task.active)):
            reasons.append('another_task_active')
        boundary=self.design_boundary()
        reasons.extend(boundary['reasons'])
        world=self.vehicle.world_snapshot()
        if any(m!='disarmed_mode' for m in design.missions):
            if self.environment is None or world is None or world.environment!=self.environment.reference or world.localization is None or world.vehicle is None:
                reasons.append('bound_environment_or_localization_unavailable')
            else:
                try:self.environment.validate_origin(world.vehicle)
                except ValueError as exc:reasons.append(str(exc))
            if self.connected_at_ns is None or self.vehicle.clock().monotonic_ns-self.connected_at_ns<self.profile.warmup_ns:
                reasons.append('simulation_motion_warmup_incomplete')
        if any(m.startswith(('navigate:','autonomy:')) for m in design.missions):
            if (self.navigation is None or self.navigation.context is None or world is None
                    or world.map!=self.navigation.context.reference):
                reasons.append('fresh_adopted_navigation_map_required')
            else:
                try:self.navigation.context.check_fresh(self.vehicle.clock())
                except ValueError as exc:reasons.append(str(exc))
        preview=None
        if any(m.startswith('motion:') for m in design.missions):
            if self.scenario_scene is None:reasons.append('explicit_scenario_scene_required')
            elif not reasons:
                try:
                    prepared,preview,anchor=self._prepare_scenario(design,expected_context,anchor)
                    if any(p.timeout_ns+8_000_000_000>self.profile.lease_ns for p in prepared.values()):
                        reasons.append('maneuver_exceeds_configured_action_lease')
                except (OSError,ValueError) as exc:reasons.append(str(exc))
        return {'eligible':not reasons,'reasons':reasons,'sha256':design.sha256,'preview':preview,'anchor':anchor,
                'context':catalog['context'],'steps':len(design.missions),'simulation_only':True}

    def start_design_checked(self, document, expected_context, expected_session, expected_anchor=None):
        if type(expected_session) is not str or expected_session!=self.vehicle.session_id:
            raise ValueError('design vehicle session changed')
        design=MissionDesign.parse(json.dumps(document),self._design_capabilities())
        if any(m.startswith('motion:') for m in design.missions) and expected_anchor is None:
            raise ValueError('parameterized execution requires the approved preview anchor')
        check=self.design_preflight(document,expected_context,anchor=expected_anchor)
        if not check['eligible']:
            raise ValueError('design preflight rejected: '+', '.join(check['reasons']))
        design=MissionDesign.parse(json.dumps(document),self._design_capabilities())
        if len(self.designs)>=64 and design.sha256 not in self.designs:
            raise ValueError('registered design budget exhausted; explicit restart required')
        from deployment.design_sequence import DesignExecution
        # Registration and starting happen in this Application event-loop mutation.
        self.designs[design.sha256]=design
        self.design_task=DesignExecution(design,expected_context,self.vehicle.clock().monotonic_ns)
        if any(m.startswith('motion:') for m in design.missions):
            self.design_task.prepared,self.design_task.preview,_=self._prepare_scenario(design,expected_context,expected_anchor)
        self._emit('design_registered',name='designed:'+design.sha256,sha256=design.sha256,
                   task_id=self.design_task.task_id,steps=list(design.missions))
        return self.design_task.view(self)

    def start_design_child(self,execution):
        if execution is not self.design_task:raise ValueError('inactive design scope')
        if execution.index in execution.prepared:
            return self.start_mission(f'scenario:{execution.design.sha256}:{execution.index}',
                _design_child=True,_scenario=execution.prepared[execution.index])
        return self.start_mission(execution.design.missions[execution.index],_design_child=True)
