"""ROS-independent sample/epoch/time fences and bounded actual trajectory."""
from collections import deque
import math

from vehicle_autonomy.contracts.core.geometry import Quaternion,Vector3
from vehicle_autonomy.world.transform.tree import rotate_vector
from .state import MAX_AGE_S,finite_vector


class Projection:
    def __init__(self,target,kind,*,limit=600):
        self.target=target;self.kind=kind;self.path=deque(maxlen=limit);self.epoch=None
        self.last_source=None;self.last_position=None;self.last_stamp=None;self.fault=None;self.resets=0

    def clear(self):self.path.clear();self.last_source=None;self.last_position=None;self.last_stamp=None;self.resets+=1

    def accept(self,source,*,received_ns,roundtrip_s,now_ns,stamp_for):
        if source.get('schema')!=1 or source.get('target')!=self.target or source.get('kind')!=self.kind:raise ValueError('vehicle identity mismatch')
        epoch=source.get('epoch')
        if not epoch:raise ValueError('vehicle origin epoch unavailable')
        if self.epoch!=epoch:
            self.clear();self.epoch=epoch;self.fault=None
        if self.fault:raise ValueError(self.fault)
        if source.get('valid') is not True:self.clear();raise ValueError(source.get('reason') or 'invalid vehicle state')
        age=source.get('age_s')
        if type(age) not in (int,float) or not math.isfinite(age) or not 0<=age+roundtrip_s+(now_ns-received_ns)/1e9<=MAX_AGE_S:
            self.clear();raise ValueError('vehicle sample or transport stale')
        sample=int(source['sample_ns']);origin=source['origin']
        if origin['frame']!='odom' or origin['axes']!='ENU' or origin['body']!='FLU' or origin['id']!=epoch:raise ValueError('unqualified coordinate origin')
        pose=source['pose'];position=finite_vector([pose['position'][k] for k in ('x','y','z')],3)
        q=finite_vector([pose['orientation'][k] for k in ('x','y','z','w')],4)
        if abs(sum(v*v for v in q)-1)>1e-6:raise ValueError('non-unit attitude quaternion')
        if self.last_source is not None:
            if sample<self.last_source:self.fault='source timestamp regressed; wait for a new source epoch or restart';self.clear();raise ValueError(self.fault)
            if sample==self.last_source:return None
            dt=(sample-self.last_source)/1e9
            maximum={'rover':3.,'copter':15.,'plane':100.}[self.kind]
            if math.dist(position,self.last_position)>2+maximum*dt:
                self.fault='position discontinuity; origin readmission required';self.clear();raise ValueError(self.fault)
        capture=received_ns-int((age+roundtrip_s)*1e9)
        stamp=stamp_for(capture)
        if type(stamp) is not int or stamp<=0 or self.last_stamp is not None and stamp<=self.last_stamp:raise ValueError('ROS timestamp missing, paused or out of order')
        raw=source['twist'];linear=Vector3(*finite_vector([raw['linear'][k] for k in ('x','y','z')],3));angular=Vector3(*finite_vector([raw['angular'][k] for k in ('x','y','z')],3))
        rotation=Quaternion(*q);inverse=Quaternion(-q[0],-q[1],-q[2],q[3])
        if source['twist_frame']=='odom':body_linear=rotate_vector(inverse,linear);body_angular=rotate_vector(inverse,angular);world_linear=linear
        elif source['twist_frame']=='base_link':body_linear=linear;body_angular=angular;world_linear=rotate_vector(rotation,linear)
        else:raise ValueError('unsupported twist frame')
        gps_stamp=None
        if source.get('gps') is not None:
            try:gps_stamp=stamp_for(received_ns-int((source['gps_age_s']+roundtrip_s)*1e9))
            except LookupError:pass
        value=dict(stamp_ns=stamp,position=position,orientation=q,body_linear=body_linear,body_angular=body_angular,world_linear=world_linear,
            sample_ns=sample,origin=origin,gps=source.get('gps'),gps_stamp_ns=gps_stamp,gps_sample_ns=source.get('gps_sample_ns'),
            age_s=age+roundtrip_s+(now_ns-received_ns)/1e9,ekf_health=source.get('ekf_health','UNKNOWN'))
        self.path.append(dict(stamp_ns=stamp,position=position,orientation=q));self.last_source=sample;self.last_position=position;self.last_stamp=stamp
        return value
