"""Bounded normalized camera-motion history, with interpolation only.

Only qualified telemetry capture times enter this history. It does not read a
transport, manufacture samples at publication time, or extrapolate orientation.
"""
from collections import deque
from dataclasses import dataclass
import math

from vehicle_autonomy.contracts.core.geometry import Pose3,Quaternion,Vector3
from vehicle_autonomy.contracts.core.quality import QualityState


class MotionPending(ValueError):
    """A fresh image is waiting for the next real sample, without extrapolation."""


class MotionHistory:
    def __init__(self):
        self.key=None;self.positions=deque(maxlen=128);self.attitudes=deque(maxlen=128)

    def update(self,telemetry,generation,now_ns,*,source_history=None):
        key=(str(generation),str(telemetry.link_session_id),str(telemetry.published_at.clock_domain_id))
        if self.key is not None and self.key!=key:
            raise ValueError('camera motion session changed; new owned sensor epoch required')
        self.key=key;changed=False
        if source_history is not None and str(source_history.link_session_id)!=key[1]:
            raise ValueError('camera motion read crossed link sessions')
        for kind,history in (('LOCAL_POSITION_NED',self.positions),('ATTITUDE',self.attitudes)):
            field=telemetry.field(kind);stamp=field.captured_at
            if (field.quality is not QualityState.VALID or stamp is None
                    or str(stamp.clock_domain_id)!=key[2] or not 0<=now_ns-stamp.monotonic_ns<=500_000_000):continue
            if source_history is None:
                from vehicle_autonomy.contracts.core.stamped import Stamped
                data=field.value.orientation_flu_enu if kind=='ATTITUDE' else field.value.position_enu_m
                samples=() if data is None else (Stamped('odom',stamp,data),)
                if history and stamp.monotonic_ns<history[-1][0]:raise ValueError('camera motion source clock regressed')
            else:samples=source_history.attitudes if kind=='ATTITUDE' else source_history.positions
            previous=-1
            for sample in samples:
                ns=sample.captured_at.monotonic_ns
                if ns<=previous:raise ValueError('camera motion source history regressed')
                previous=ns
                if (str(sample.captured_at.clock_domain_id)!=key[2] or str(sample.frame_id)!='odom'
                        or not 0<=now_ns-ns<=1_500_000_000):continue
                data=sample.value;values=(data.x,data.y,data.z,data.w) if kind=='ATTITUDE' else (data.x,data.y,data.z)
                if not history or ns>history[-1][0]:history.append([ns,*values]);changed=True
            while history and now_ns-history[0][0]>1_500_000_000:history.popleft()
        return changed

    def envelope(self,now_ns):
        return dict(schema=1,world_generation=self.key[0],link_session_id=self.key[1],clock_domain_id=self.key[2],
            published_ns=now_ns,positions=list(self.positions),attitudes=list(self.attitudes))


@dataclass(frozen=True)
class MotionMatch:
    pose: Pose3
    key: tuple
    attitude_rate_hz: float
    attitude_bracket_ns: tuple
    position_bracket_ns: tuple


def match_motion(value,capture_ns,now_ns,*,expected_key=None,max_distance_ns=125_000_000,
                 max_span_ns=150_000_000,min_attitude_rate_hz=8.):
    if (type(value) is not dict or value.get('schema')!=1 or type(value.get('published_ns')) is not int
            or not 0<=now_ns-value['published_ns']<=500_000_000
            or not 0<=now_ns-capture_ns<=500_000_000):raise ValueError('camera motion publication/capture stale')
    key=tuple(value.get(k) for k in ('world_generation','link_session_id','clock_domain_id'))
    if any(not isinstance(k,str) or not k for k in key) or expected_key is not None and key!=expected_key:
        raise ValueError('camera motion provenance changed')
    def bracket(name,length):
        rows=value.get(name)
        if type(rows) is not list or not 2<=len(rows)<=128:raise ValueError(name+' history warming up')
        previous=-1
        for row in rows:
            if (type(row) is not list or len(row)!=length or type(row[0]) is not int
                    or not previous<row[0]<=value['published_ns']
                    or any(type(n) not in (int,float) or not math.isfinite(n) for n in row[1:])):
                raise ValueError('invalid camera '+name+' history')
            previous=row[0]
        before=next((r for r in reversed(rows) if r[0]<=capture_ns),None)
        after=next((r for r in rows if r[0]>=capture_ns),None)
        if before is None:raise ValueError(name+' starts after original image capture')
        if after is None:raise MotionPending(name+' waiting for capture bracket')
        if (max(capture_ns-before[0],after[0]-capture_ns)>max_distance_ns
                or after[0]-before[0]>max_span_ns):raise ValueError(name+' interpolation gap too wide')
        ratio=0. if before[0]==after[0] else (capture_ns-before[0])/(after[0]-before[0])
        return rows,before,after,ratio
    positions,p0,p1,t=bracket('positions',4)
    attitudes,q0,q1,u=bracket('attitudes',5)
    recent=[r for r in attitudes if 0<=q1[0]-r[0]<=1_000_000_000]
    if len(recent)<4:raise ValueError('attitude rate warming up')
    rate=(len(recent)-1)*1e9/(recent[-1][0]-recent[0][0])
    if rate<min_attitude_rate_hz:raise ValueError('attitude rate insufficient')
    a=Quaternion(*q0[1:]);b=Quaternion(*q1[1:])
    av=(a.x,a.y,a.z,a.w);bv=(b.x,b.y,b.z,b.w);dot=sum(x*y for x,y in zip(av,bv))
    if dot<0:bv=tuple(-x for x in bv);dot=-dot
    if dot>.9995:weights=(1-u,u)
    else:
        angle=math.acos(min(1.,dot));denominator=math.sin(angle)
        weights=(math.sin((1-u)*angle)/denominator,math.sin(u*angle)/denominator)
    q=[weights[0]*x+weights[1]*y for x,y in zip(av,bv)];norm=math.sqrt(sum(x*x for x in q))
    pose=Pose3(Vector3(*(x+t*(y-x) for x,y in zip(p0[1:],p1[1:]))),Quaternion(*(x/norm for x in q)))
    return MotionMatch(pose,key,rate,(q0[0],q1[0]),(p0[0],p1[0]))
