"""Native Nav2 outputs -> one existing Rover Typed Effect stream.

Motion remains behind ActionRuntime/Execution/Authority/Safety/the sole writer.
An independent managed job owns the native Goal servers. Both vehicle parking
and the external producer exit must be proved before the resources are free.
"""
from dataclasses import dataclass,field,replace
from datetime import datetime,timedelta
import math
from uuid import uuid4
from vehicle_autonomy.actions.common.standard import ContextFactory
from vehicle_autonomy.actions.rover.standard import RoverStream,RoverStreamFactory,DriveParameters
from vehicle_autonomy.actions.navigation.native_job import NativeNavigationJob
from vehicle_autonomy.contracts.algorithms import NATIVE_NAVIGATION_RESOURCES as RESOURCES
from vehicle_autonomy.contracts.action import ActionKind,ActionSafety
from vehicle_autonomy.contracts.action_ports import ActionAdmissionRejected
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.decision import ActionSpec,ActionDecision,ActionOutcome,ExitDecision
from vehicle_autonomy.contracts.effects.vehicle import TwistTargetEffect,StopMotionEffect,ModeEffect
from vehicle_autonomy.contracts.streams import DataKind
from vehicle_autonomy.engine.navigation.inputs import NavigationInput,RoverNavigationInputs,NavigationEvidenceUnavailable
from vehicle_autonomy.engine.navigation.mailbox import NavigationBinding,NavigationCommand,NavigationMailbox


@dataclass(frozen=True,slots=True)
class NavigateParameters:
    x_m: float=field(metadata={'minimum':-5.,'maximum':5.})
    y_m: float=field(metadata={'minimum':-5.,'maximum':5.})
    map_epoch: str=field(metadata={'minLength':1,'maxLength':256})
    yaw_rad: float=field(default=0.,metadata={'minimum':-math.pi,'maximum':math.pi})


def _point(value):
    if type(value) is not dict or set(value)!={'monotonic_ns','utc','clock_domain_id'}:raise ValueError('original typed navigation time required')
    return TimePoint(value['monotonic_ns'],datetime.fromisoformat(value['utc']),value['clock_domain_id'])


def _command(value):
    if type(value) is not dict or set(value)!={'binding','sequence','source_stamp_ns','captured_at','received_at','speed_mps','yaw_rate_rad_s'}:raise ValueError('strict native final source command required')
    return NavigationCommand(NavigationBinding(**value['binding']),value['sequence'],value['source_stamp_ns'],_point(value['captured_at']),_point(value['received_at']),value['speed_mps'],value['yaw_rate_rad_s'])


class NativeRoverNavigationFactory(ContextFactory):
    def __init__(self,identity,*,security_environment,scan_source,slam_source,pose_reader,clock,write_fence,cohort_factory):
        self.identity=identity;self.resource_store=identity.load();self.security=dict(security_environment)
        self.scan_source=scan_source;self.slam_source=slam_source;self.pose_reader=pose_reader;self.clock=clock;self.write_fence=write_fence;self.cohort_factory=cohort_factory
    def prerequisites(self,w,session):
        requirements=[]
        for kind,age in ((DataKind.SCAN,300_000_000),(DataKind.SLAM_POSE,500_000_000),(DataKind.MAP,10_000_000_000),(DataKind.TRANSFORM,500_000_000)):
            source=self.scan_source if kind is DataKind.SCAN else self.slam_source
            found=[s.header for s in w.streams if s.header.kind is kind and s.header.source_id==source]
            if len(found)!=1:raise NavigationEvidenceUnavailable('selected native algorithm inputs are unavailable')
            requirements.append(NavigationInput(found[0],age))
        return RoverNavigationInputs(world_generation=str(w.version.generation_id),vehicle_session=session,requirements=tuple(requirements))
    def start_with_context(self,p,w,ctx):
        if ctx.target_kind!='rover' or not ctx.owned_simulation or not all((ctx.action_id,ctx.vehicle_session,ctx.world_generation)):raise ActionAdmissionRejected('native navigation requires bound owned Rover context')
        if (to_json_value(ctx.metadata) or {}).get('native_input_fence')!=self.write_fence.identity:raise ActionAdmissionRejected('native source fence is not installed on this vehicle driver')
        return NativeNavigationPreparation(self,p,ctx)
    def create_ready(self,p,w,ctx):
        if str(w.version.generation_id)!=ctx.world_generation or w.vehicle is None or w.vehicle.telemetry is None or str(w.vehicle.telemetry.link_session_id)!=ctx.vehicle_session:raise ActionAdmissionRejected('native vehicle epoch changed before dispatch')
        if ctx.target_kind!='rover' or not ctx.owned_simulation or not all((ctx.action_id,ctx.vehicle_session,ctx.world_generation)):raise ActionAdmissionRejected('native navigation requires bound owned Rover context')
        if (to_json_value(ctx.metadata) or {}).get('native_input_fence')!=self.write_fence.identity:raise ActionAdmissionRejected('native source fence is not installed on this vehicle driver')
        now=self.clock();guard=self.prerequisites(w,ctx.vehicle_session);guard.validate(w,now)
        if p.map_epoch!=guard.map_epoch:raise ActionAdmissionRejected('requested native map epoch is not current')
        v=w.vehicle.reported_twist.value
        if math.hypot(v.linear.x,v.linear.y)>.1:raise ActionAdmissionRejected('navigation admission requires observed stationary Rover')
        RoverStreamFactory('Drive').validate_context(DriveParameters(0.,0.),w,ctx)
        goal_id=uuid4().hex;goal=dict(goal_id=goal_id,action_id=ctx.action_id,target_id=ctx.target_id,vehicle_session=ctx.vehicle_session,world_generation=ctx.world_generation,map_epoch=p.map_epoch,x_m=p.x_m,y_m=p.y_m,yaw_rad=p.yaw_rad,provider_id=self.identity.provider_id,provider_epoch=self.identity.provider_epoch)
        self.write_fence.admit(ctx.action_id,guard)
        try:job=ctx.external_jobs.start(lambda:NativeNavigationJob(self.identity,goal,security_environment=self.security,world_name=self.identity.provider_epoch,clock_domain=now.clock_domain_id,cohort_factory=self.cohort_factory))
        except BaseException:
            self.write_fence.close(ctx.action_id);raise
        return NativeRoverNavigation(p,w,ctx,job,guard,goal,now,self.clock,self.pose_reader,self.write_fence)


class NativeNavigationPreparation:
    """Input admission within the SAME Action/lease, before any ROS Goal/job.

    Waiting is not a retry of a dispatched operation. Once a job/effect exists,
    the delegate applies the strict source deadman and exit barriers.
    """
    def __init__(self,factory,p,ctx):self.factory=factory;self.p=p;self.ctx=ctx;self.delegate=None
    def tick(self,w):return self.tick_with_results(w,())
    def tick_with_results(self,w,results):
        if self.delegate is None:
            try:self.delegate=self.factory.create_ready(self.p,w,self.ctx)
            except NavigationEvidenceUnavailable as exc:return ActionDecision(ActionOutcome.RUNNING,feedback={'phase':'WAITING_BEFORE_DISPATCH','reason':str(exc)})
            except (ValueError,ActionAdmissionRejected) as exc:return ActionDecision(ActionOutcome.FAILED,error=str(exc))
        return self.delegate.tick_with_results(w,results)
    def exit(self,w,reason):return self.exit_with_results(w,reason,())
    def exit_with_results(self,w,reason,results):
        return self.delegate.exit_with_results(w,reason,results) if self.delegate else ExitDecision(True)
    def abandon(self):
        if self.delegate:self.delegate.abandon()
    def recovery_descriptor(self):
        return self.delegate.recovery_descriptor() if self.delegate else {'protocol':'native','phase':'NOT_DISPATCHED','job_id':None}
    def reconcile_exit(self):return self.delegate.reconcile_exit() if self.delegate else ActionSafety(True)


class NativeRoverNavigation:
    def __init__(self,p,w,ctx,job,guard,goal,opened,clock,pose_reader,write_fence):
        self.parameters=p;self.job=job;self.inputs=guard;self.goal=goal;self.opened=opened;self.clock=clock;self.pose_reader=pose_reader;self.write_fence=write_fence
        self.stream=RoverStream('Drive',DriveParameters(0.,0.),w,ctx);self.mailbox=None;self.last_sequence=-1;self.moving=False;self.exiting=False;self.vehicle_complete=False
    def tick(self,w):return self.tick_with_results(w,())
    def tick_with_results(self,w,results):
        now=self.clock()
        try:
            value=self.job.poll();state=value['state'];feedback=value.get('feedback') or {}
            candidate=feedback.get('native_result') if feedback.get('phase')=='EXITING' else (value.get('result') or {}).get('native_result')
            if state in ('FAILED','UNKNOWN','CANCELLED') or feedback.get('phase')=='EXITING' and not (candidate and candidate.get('state')=='SUCCEEDED'):return ActionDecision(ActionOutcome.FAILED,error=value.get('error') or (candidate or {}).get('error') or value.get('detail') or 'native outcome not successful')
            expiry=self.inputs.validate(w,now)
            if candidate and candidate.get('state')=='SUCCEEDED':
                pose=self.pose_reader(w,self.inputs.map_epoch)
                distance=math.hypot(pose.position.x-self.parameters.x_m,pose.position.y-self.parameters.y_m)
                q=pose.orientation;yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
                angle=abs(math.atan2(math.sin(yaw-self.parameters.yaw_rad),math.cos(yaw-self.parameters.yaw_rad)))
                if distance>.25 or angle>.15:return ActionDecision(ActionOutcome.FAILED,error=f'native result lacks independent fresh World goal proof: distance_m={distance:.6f}, yaw_error_rad={angle:.6f}')
                return ActionDecision(ActionOutcome.SUCCEEDED,result=dict(map_epoch=self.parameters.map_epoch,distance_m=distance,yaw_error_rad=angle,native_result=candidate))
            if state in ('FAILED','UNKNOWN','CANCELLED') or feedback.get('phase')=='EXITING':return ActionDecision(ActionOutcome.FAILED,error=value.get('error') or (candidate or {}).get('error') or value.get('detail') or 'native outcome not successful')
            raw=feedback.get('command');new=False
            if raw is not None:
                command=_command(raw);b=command.binding
                expected=(self.goal['action_id'],self.goal['target_id'],self.goal['provider_id'],self.goal['provider_epoch'],self.goal['vehicle_session'],self.goal['world_generation'],self.goal['goal_id'],now.clock_domain_id)
                if (b.action_id,b.target_id,b.provider_id,b.provider_epoch,b.vehicle_session,b.world_generation,b.goal_id,b.clock_domain)!=expected:raise ValueError('native command escaped sealed Action/Goal/session binding')
                age=now.monotonic_ns-command.captured_at.monotonic_ns
                if not self.stream.touched and age>=200_000_000:
                    return ActionDecision(ActionOutcome.RUNNING,feedback={'phase':'WAITING_FIRST_FRESH_NATIVE_COMMAND','rejected_source_age_ns':age})
                if self.mailbox is None:self.mailbox=NavigationMailbox(b,self.opened)
                if command.sequence>self.last_sequence:
                    self.mailbox.accept(command,now);self.last_sequence=command.sequence;new=True
                elif command.sequence<self.last_sequence:raise ValueError('native command sequence regressed')
            if self.mailbox is None:return ActionDecision(ActionOutcome.RUNNING,feedback={'phase':feedback.get('phase','BOOTING')})
            try:command=self.mailbox.latest(now)
            except ValueError:
                if self.moving:raise
                v=w.vehicle.reported_twist.value
                if math.hypot(v.linear.x,v.linear.y)>.1:raise ValueError('movement without an active native input')
                return ActionDecision(ActionOutcome.RUNNING,feedback={'phase':'WAITING_INITIAL_NATIVE_INPUT'})
            if not new:return ActionDecision(ActionOutcome.RUNNING,feedback={'phase':feedback.get('phase')})
            if feedback.get('phase')!='ACTIVE':
                if self.stream.touched:raise ValueError('native macro left ACTIVE after vehicle dispatch')
                if feedback.get('phase') not in ('PREPARING','PREPARE_CANCEL','CONTROLLER_PREPARE'):raise ValueError('unrecognized native macro phase')
                return ActionDecision(ActionOutcome.RUNNING,feedback={'phase':'PREPARING_NATIVE_SOURCE'})
            if not self.moving and (abs(command.speed_mps)>.06 or abs(command.yaw_rate_rad_s)>.1):raise ValueError('first actual vehicle input must ramp from stationary state')
            deadline=min(expiry,command.captured_at.monotonic_ns+200_000_000)
            # A known nearly-expired cut cannot survive the queued owner cycle.
            # Do not emit/renew it; a later independently fresh cut may proceed.
            if deadline-now.monotonic_ns<60_000_000:return ActionDecision(ActionOutcome.RUNNING,feedback={'phase':'WAITING_FRESH_WRITE_EVIDENCE','remaining_ns':deadline-now.monotonic_ns})
            self.stream.update_input(DriveParameters(command.speed_mps,command.yaw_rate_rad_s));self.stream.refresh_ns=0
            decision=self.stream.tick_with_results(w,results)
            if decision.effects:self.moving=self.moving or abs(command.speed_mps)+abs(command.yaw_rate_rad_s)>0
            deadline=min(expiry,command.captured_at.monotonic_ns+200_000_000)
            valid=replace(now,monotonic_ns=deadline,utc=now.utc+timedelta(microseconds=(deadline-now.monotonic_ns)//1000))
            return replace(decision,valid_until=valid,feedback={'phase':feedback.get('phase'),'native_source_ns':command.source_stamp_ns,'native_age_ns':now.monotonic_ns-command.captured_at.monotonic_ns})
        except NavigationEvidenceUnavailable as exc:
            if not self.stream.touched:return ActionDecision(ActionOutcome.RUNNING,feedback={'phase':'WAITING_VALID_INITIAL_DATA','reason':str(exc)})
            return ActionDecision(ActionOutcome.FAILED,error='native input rejected: '+str(exc))
        except (ValueError,KeyError,TypeError,OSError) as exc:return ActionDecision(ActionOutcome.FAILED,error='native input rejected: '+str(exc))
    def exit(self,w,reason):return self.exit_with_results(w,reason,())
    def exit_with_results(self,w,reason,results):
        if not self.exiting:
            self.exiting=True;self.write_fence.close(self.goal['action_id'])
            if self.mailbox:self.mailbox.close()
            value=self.job.poll()
            if value['state']=='RUNNING' and (value.get('feedback') or {}).get('phase')!='EXITING':self.job.cancel()
        decision=self.stream.exit_with_results(w,reason,results);self.vehicle_complete=decision.complete
        state=self.job.poll()['state'];terminal=state in ('SUCCEEDED','FAILED','CANCELLED')
        if decision.complete and state=='UNKNOWN':return ExitDecision(True,decision.effects,ActionSafety(False,False,'native producer shutdown UNKNOWN'))
        if decision.complete and terminal:self.job.close()
        return ExitDecision(decision.complete and terminal,decision.effects)
    def abandon(self):
        self.write_fence.close(self.goal['action_id'])
        if self.mailbox:self.mailbox.close()
        self.job.cancel();self.job.close()
    def recovery_descriptor(self):return self.job.recovery_descriptor()
    def reconcile_exit(self):
        if self.vehicle_complete and self.job.reconcile()['state'] in ('SUCCEEDED','FAILED','CANCELLED'):return ActionSafety(True,False,'native producer shutdown reconciled')
        return None


def register_native_navigation(registry,factory):
    registry.register_typed(ActionSpec('NavigateToPose',NavigateParameters,frozenset(),kind=ActionKind.GOAL,vehicle_types=frozenset({'rover'}),resources=RESOURCES,effect_types=(TwistTargetEffect,StopMotionEffect,ModeEffect),external_lifecycle='managed',effect_ttl_overrides={'ModeEffect':5_000_000_000},default_timeout_ns=85_000_000_000,description='原生 Nav2 地图导航；保留 Execution/Safety/Authority 边界',success_semantics='Native Goal result AND independent fresh World map pose, followed by parked vehicle and stopped native producer cohort.'),factory)
