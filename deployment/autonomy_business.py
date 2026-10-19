"""Application route/inspection orchestration; no command port or ROS imports."""
from __future__ import annotations
import math
from uuid import uuid4
from contracts.core.quality import QualityState
from .goal_navigation import TERMINAL


class AutonomyBusiness:
    def __init__(self,app,name):
        self.catalog=app.autonomy_recipes;self.catalog.check()
        if name not in self.catalog.recipes:raise ValueError('unregistered autonomy recipe')
        self.recipe=self.catalog.recipes[name]
        self.task_id='autonomy:'+uuid4().hex;self.status='RUNNING';self.error=None
        self.deadline_ns=app.vehicle.clock().monotonic_ns+int(self.recipe.total_timeout_s*1e9)
        self.index=0;self.checkpoints=[];self.inspections=[];self.pending=None;self.cleanup_id=None
        self.frame_epoch=app.vehicle.world_epoch;self.environment=app.environment.reference
        self.target=None
        if self.recipe.inspection_label:
            world=app.vehicle.world_snapshot()
            choices=[]
            for obj in world.objects:
                try:
                    if (obj.label==self.recipe.inspection_label and obj.quality==QualityState.VALID
                            and obj.confidence>=.5 and obj.position.frame_id=='odom'
                            and 0<=app.vehicle.clock().elapsed_ns_since(obj.position.captured_at)<=500_000_000):
                        choices.append(obj)
                except ValueError:continue
            if not choices:raise ValueError('inspection_target_unavailable')
            self.target=min(choices,key=lambda o:(-o.confidence,str(o.object_id)))
            self._target(app)
            goal=app.navigation_goals.goals[self.recipe.inspection_at]
            if goal.frame!='odom':raise ValueError('object inspection currently requires an odom approach goal')
            p=goal.resolve(app.environment);q=self.target.position.value
            if not 1.0<=math.hypot(p.x-q.x,p.y-q.y)<=2:
                raise ValueError('inspection approach must be a registered 1..2 metre standoff')
        self.navigation=app._launch_goal(self.recipe.goals[0])

    @property
    def active(self):return self.status not in TERMINAL

    def _target(self,app):
        world=app.vehicle.world_snapshot();now=app.vehicle.clock()
        matches=[] if world is None else [o for o in world.objects if (o.object_id,o.producer_id)==(self.target.object_id,self.target.producer_id)]
        if not matches:raise ValueError('inspection_target_lost_or_expired')
        obj=matches[0]
        if (obj.label!=self.recipe.inspection_label or obj.quality!=QualityState.VALID or obj.confidence<.5
                or obj.position.frame_id!='odom' or not 0<=now.elapsed_ns_since(obj.position.captured_at)<=500_000_000):
            raise ValueError('inspection_target_lost_or_expired')
        p,q=obj.position.value,self.target.position.value
        if math.hypot(p.x-q.x,p.y-q.y)>.2:raise ValueError('inspection_target_moved')
        return obj

    def cancel(self,app,error=None):
        if not self.active or self.pending is not None:return
        self.pending='FAILED' if error else 'CANCELLED';self.error=error;self.status='CANCELLING'
        if self.navigation.active:self.navigation.cancel(app,error=error)

    def _finish(self,app,status,error=None):
        self.status,self.error=status,error
        app._emit('autonomy_business_finished',**self.view(app))

    def tick(self,app):
        if not self.active:return
        if self.pending is None:
            try:
                self.catalog.check()
                if app.vehicle.world_epoch!=self.frame_epoch or app.environment is None or app.environment.reference!=self.environment:
                    raise ValueError('autonomy_environment_or_epoch_changed')
                if app.vehicle.clock().monotonic_ns>self.deadline_ns:raise ValueError('autonomy_business_deadline')
                if self.target is not None and not self.inspections:self._target(app)
            except (OSError,ValueError,TypeError) as exc:self.cancel(app,str(exc))
        if self.pending is not None:
            if self.navigation.active:return
            if self.cleanup_id is None:
                try:
                    child=app.start_mission('safe_recovery',_navigation_child=True)
                    self.cleanup_id=child['task_id'];self.status='CLEANUP'
                except (OSError,ValueError,RuntimeError) as exc:
                    self._finish(app,'FAILED',(self.error or 'cancel')+'; cleanup_unconfirmed: '+str(exc))
            else:
                child=app._mission_status()
                if child and child['task_id']==self.cleanup_id and child['status'] in TERMINAL:
                    if child['status']=='SUCCEEDED':self._finish(app,self.pending,self.error)
                    else:self._finish(app,'FAILED',(self.error or 'cancel')+'; cleanup_unconfirmed: '+str(child['error']))
            return
        if self.navigation.status not in TERMINAL:return
        if self.navigation.status!='SUCCEEDED':
            self.cancel(app,self.navigation.error or 'autonomy_navigation_failed');return
        goal=self.recipe.goals[self.index]
        self.checkpoints.append({'goal':goal,'navigation_task_id':self.navigation.task_id,
            'status':self.navigation.status,'attempts':self.navigation.attempt,'captured_ns':app.vehicle.clock().monotonic_ns})
        if self.recipe.inspection_at==goal and not self.inspections:
            try:
                obj=self._target(app);world=app.vehicle.world_snapshot()
                twist=world.localization.twist.value
                if world.vehicle.operation.armed or math.hypot(twist.linear.x,twist.linear.y)>.1 or abs(twist.angular.z)>.15:
                    raise ValueError('inspection_requires_observed_disarmed_stop')
                self.inspections.append({'goal':goal,'object_id':str(obj.object_id),'producer':str(obj.producer_id),
                    'observation_id':str(obj.source_observation_id),'captured_ns':obj.position.captured_at.monotonic_ns,
                    'position':[obj.position.value.x,obj.position.value.y,obj.position.value.z],
                    'world_version':world.version.revision,'frame_epoch':str(self.frame_epoch)})
            except (ValueError,TypeError) as exc:self.cancel(app,str(exc));return
        self.index+=1
        if self.index==len(self.recipe.goals):self._finish(app,'SUCCEEDED');return
        try:self.navigation=app._launch_goal(self.recipe.goals[self.index])
        except (OSError,ValueError,TypeError,RuntimeError) as exc:self.cancel(app,str(exc))

    def view(self,app):
        nav=self.navigation.view(app)
        return {**nav,'task_id':self.task_id,'mission':'autonomy:'+self.recipe.name,'status':self.status,
            'error':self.error,'recipe_sha256':self.catalog.sha256,'deadline_ns':self.deadline_ns,
            'checkpoint_index':self.index,'checkpoints':self.checkpoints,'inspections':self.inspections,
            'navigation_task_id':self.navigation.task_id,'cleanup_id':self.cleanup_id}
