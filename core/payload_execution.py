"""Dedicated non-vehicle Execution: explicit Safety and final mutation fence."""
from dataclasses import dataclass
import math
from contracts.core.quality import QualityState
from contracts.effects.payload import PayloadEffectEnvelope

@dataclass(frozen=True,slots=True)
class PayloadSafetyPolicy:
    allowed_producer_prefixes:tuple[str,...]
    allowed_labels:tuple[str,...]=('bucket_1','bucket_2','bucket_3')
    max_target_age_ns:int=1_000_000_000
    max_vehicle_age_ns:int=3_000_000_000
    max_alignment_m:float=.3
    max_speed_mps:float=.15

    def __post_init__(self):
        if not self.allowed_producer_prefixes or any(not p for p in self.allowed_producer_prefixes):raise ValueError('explicit payload sources required')
        if any(type(v) is not int or v<=0 for v in (self.max_target_age_ns,self.max_vehicle_age_ns)) or any(not math.isfinite(v) or v<=0 for v in (self.max_alignment_m,self.max_speed_mps)):raise ValueError('invalid payload Safety')

    def reason(self,envelope,world,now):
        effect=envelope.effect
        if world is None or world.environment!=effect.environment or world.vehicle is None or world.localization is None:return 'payload_world_unavailable'
        vehicle=world.vehicle;loc=world.localization
        if vehicle.health.quality is not QualityState.VALID or not vehicle.operation.armed or vehicle.operation.native_mode!='ARDUPILOT_CUSTOM_4':return 'payload_armed_guided_required'
        if loc.quality is not QualityState.VALID or loc.pose.frame_id!='odom' or loc.twist is None or loc.twist.frame_id!='odom':return 'payload_localization_invalid'
        target=next((o for o in world.objects if o.object_id==effect.target_id and str(o.producer_id)==effect.producer_id),None)
        if target is None or target.position.frame_id!='odom' or target.quality is not QualityState.VALID or target.label not in self.allowed_labels or target.confidence<.5:return 'payload_target_invalid'
        if not any(effect.producer_id.startswith(prefix) for prefix in self.allowed_producer_prefixes):return 'payload_source_untrusted'
        try:
            if any(not 0<=now.elapsed_ns_since(at)<=self.max_target_age_ns for at in (target.position.captured_at,effect.target_captured_at)):return 'payload_target_stale'
            if any(not 0<=now.elapsed_ns_since(at)<=self.max_vehicle_age_ns for at in (loc.pose.captured_at,loc.twist.captured_at,world.published_at)):return 'payload_vehicle_stale'
            if target.position.captured_at<effect.target_captured_at:return 'payload_target_regressed'
        except ValueError:return 'payload_clock_mismatch'
        target_pose=target.position.value;p=loc.pose.value.position;v=loc.twist.value.linear
        if math.dist((target_pose.x,target_pose.y,target_pose.z),(effect.target_position.x,effect.target_position.y,effect.target_position.z))>.1:return 'payload_target_moved'
        if math.hypot(p.x-target_pose.x,p.y-target_pose.y)>self.max_alignment_m or not 1<=p.z-target_pose.z<=2:return 'payload_not_aligned'
        if math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z)>self.max_speed_mps or abs(loc.twist.value.angular.z)>.15:return 'payload_motion_unsafe'
        return None

class PayloadExecution:
    def __init__(self,authority,port,safety,world_reader):
        if not isinstance(safety,PayloadSafetyPolicy):raise TypeError('explicit payload SafetyPolicy required')
        self.authority=authority;self.port=port;self.safety=safety;self.world=world_reader
        self.envelopes={};self.results={};self.pending={};self.awaiting={}
    def _result(self,key,phase,reason=None):
        self.results[key]={'phase':phase,'reason':reason,'command_id':'payload:'+key}
    def _reason(self,envelope,now,*,admission=False):
        try:
            if envelope.deadline.elapsed_ns_since(now)<=0 or now.elapsed_ns_since(envelope.created_at)<0:return 'payload_deadline_invalid'
        except ValueError:return 'payload_clock_mismatch'
        if admission:
            world=self.world.snapshot()
            if world is None or not any(o.object_id==envelope.effect.target_id and str(o.source_observation_id)==envelope.effect.target_observation_id for o in world.objects):return 'payload_observation_identity_mismatch'
        return self.authority.admission_reason(envelope.run_id,envelope.action_instance_id,now) or self.safety.reason(envelope,self.world.snapshot(),now)
    def dispatch(self,envelope,now):
        if not isinstance(envelope,PayloadEffectEnvelope):raise TypeError('PayloadExecution only accepts payload envelopes')
        key=str(envelope.effect_id)
        if key in self.envelopes:
            if self.envelopes[key]!=envelope:raise ValueError('payload Effect ID reused')
            return self.results[key]
        self.envelopes[key]=envelope
        with self.authority.lock:
            reason=self._reason(envelope,now,admission=True)
            if reason:self._result(key,'REJECTED',reason)
            else:
                self.pending[key]=(self.authority.authorization_generation,self.authority.send_generation,self.authority.link_session_id)
                self._result(key,'ACCEPTED')
        return self.results[key]
    def cancel(self,run_id):
        for key in tuple(self.pending):
            if self.envelopes[key].run_id==run_id:self.pending.pop(key);self._result(key,'CANCELLED','cancelled_before_mutation')
    def tick(self,now):
        for key,fence in tuple(self.pending.items()):
            envelope=self.envelopes[key]
            with self.authority.lock:
                reason=self._reason(envelope,now)
                if fence!=(self.authority.authorization_generation,self.authority.send_generation,self.authority.link_session_id):reason='payload_generation_or_session_changed'
                if reason:self._result(key,'REJECTED',reason)
                else:
                    try:self.port.release(envelope,now)
                    except (ValueError,RuntimeError) as exc:self._result(key,'REJECTED',str(exc))
                    else:self._result(key,'ACKNOWLEDGED');self.awaiting[key]=now
                self.pending.pop(key)
        world=self.world.snapshot()
        for key,mutated in tuple(self.awaiting.items()):
            envelope=self.envelopes[key];effect=envelope.effect
            marker=effect.payload_id+'@'+effect.target_id
            found=world and any(o.object_id==self.port.state_producer_id+':'+marker and o.label=='sim_payload_released' and o.position.frame_id=='odom' and o.quality is QualityState.VALID and o.confidence>=.5 and o.position.value==effect.target_position and o.position.captured_at>mutated for o in world.objects)
            if found:self._result(key,'COMPLETED');self.awaiting.pop(key)
            elif now.elapsed_ns_since(envelope.deadline)>=0:self._result(key,'UNKNOWN','payload_observation_deadline');self.awaiting.pop(key)
    def status(self,key):return self.results.get(key)
