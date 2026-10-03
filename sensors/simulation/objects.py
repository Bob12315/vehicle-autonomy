"""Replaceable, read-only Gazebo object producer, independent of acceptance Oracle."""
from datetime import datetime,timezone
from dataclasses import dataclass
from collections import deque
import hashlib
import re
from threading import Lock
import time
import tomllib
from uuid import uuid4
from contracts.core.geometry import Transform3, Quaternion, Vector3
from contracts.core.primitives import SchemaVersion
from contracts.core.quality import QualityState
from contracts.core.time import TimePoint
from contracts.sensor import Observation, DetectedObject
from core.transform import rotate_vector

@dataclass(frozen=True,slots=True)
class ObjectCalibration:
    world: str
    transform: Transform3
    source: str
    version: str
    models: tuple[str,...]=('target_1','target_2','target_3')

    @classmethod
    def load(cls,path):
        raw=path.read_bytes();d=tomllib.loads(raw.decode())
        if set(d)!={'schema','world','frame','translation','rotation','source','models'} or d['schema']!=1 or d['frame']!='odom' or not d['source'].strip():raise ValueError('explicit simulation world/odom calibration required')
        if not re.fullmatch(r'[a-zA-Z0-9_]+',d['world']) or not d['models'] or len(set(d['models']))!=len(d['models']) or any(m not in ('target_1','target_2','target_3') for m in d['models']):raise ValueError('invalid object whitelist/world')
        return cls(d['world'],Transform3(Vector3(*d['translation']),Quaternion(*d['rotation'])),d['source'],hashlib.sha256(raw).hexdigest(),tuple(d['models']))

class GazeboClockBridge:
    """Map paired Gazebo SIM/REAL clocks into the local monotonic epoch.

    Uses only bracketed clock samples, never assumes physical simulation runs
    exactly as fast as wall time. The initial loopback receive anchors REAL.
    """
    def __init__(self):
        self.samples=deque(maxlen=4096);self.anchor=None;self.error=None
    def ingest(self,sim_ns,real_ns,received_ns):
        if self.error:return
        if self.samples and (sim_ns<self.samples[-1][0] or real_ns<self.samples[-1][1]):
            self.error='gazebo_clock_regressed';return
        if self.anchor is None:self.anchor=(real_ns,received_ns)
        if self.samples and sim_ns==self.samples[-1][0]:return
        self.samples.append((sim_ns,real_ns))
    def capture(self,sim_ns):
        if self.error or not self.samples:return None
        if sim_ns<self.samples[0][0] or sim_ns>self.samples[-1][0]:return None
        for index in range(len(self.samples)-1,-1,-1):
            sim,real=self.samples[index]
            if sim==sim_ns:return self.anchor[1]+real-self.anchor[0]
            if sim<sim_ns:
                upper_sim,upper_real=self.samples[index+1]
                if upper_sim-sim>100_000_000:return None
                mapped=real+int((upper_real-real)*(sim_ns-sim)/(upper_sim-sim))
                return self.anchor[1]+mapped-self.anchor[0]
        return None

class ObjectProjector:
    """Per-source speed-one clock anchor; duplicates retain their capture age."""
    def __init__(self,calibration,clock_domain):
        self.calibration=calibration
        self.domain=clock_domain
        self.producer='sim.objects:'+calibration.version[:16]+':'+uuid4().hex
        self.anchor_sim=None;self.anchor_host=None;self.previous=None;self.sequence=0
        self.known={};self.error=None

    def project(self,sim_ns,received_ns,positions,*,capture_ns=None):
        if self.error:return ()
        if self.previous is not None and sim_ns<self.previous:
            self.error='simulation_clock_regressed';return self.invalidate(received_ns)
        if sim_ns==self.previous:return ()
        if self.anchor_sim is None:self.anchor_sim,self.anchor_host=sim_ns,received_ns
        capture=self.anchor_host+sim_ns-self.anchor_sim if capture_ns is None else capture_ns
        if capture>received_ns+100_000_000 or abs((received_ns-capture))>3_000_000_000:
            self.error='simulation_clock_skew';return self.invalidate(received_ns)
        # Early callback jitter must never create a future stamp.
        capture=min(capture,received_ns)
        self.previous=sim_ns
        output=[]
        for model in self.calibration.models:
            present=model in positions
            if not present and model not in self.known:continue
            if present:
                value=rotate_vector(self.calibration.transform.rotation,positions[model]);t=self.calibration.transform.translation
                self.known[model]=Vector3(value.x+t.x,value.y+t.y,value.z+t.z)
            output.append(self._observation(model,self.known[model],capture,received_ns,QualityState.VALID if present else QualityState.UNAVAILABLE))
        return tuple(output)

    def _observation(self,model,position,capture,receive,quality):
        self.sequence+=1
        return Observation(f'{self.producer}:{self.sequence}',SchemaVersion(1,0),self.producer,self.sequence,
            TimePoint(capture,utc=datetime.now(timezone.utc),clock_domain_id=self.domain),TimePoint(receive,utc=datetime.now(timezone.utc),clock_domain_id=self.domain),quality,
            DetectedObject(model,'bucket_'+model.rsplit('_',1)[-1],position,1.0),'odom')

    def invalidate(self,now):
        return tuple(self._observation(m,p,now,now,QualityState.UNAVAILABLE) for m,p in self.known.items())

class GazeboObjectSource:
    """Bounded latest packet; no service calls, commands, or Oracle dependency."""
    def __init__(self,calibration,clock_domain):
        from gz.msgs10.pose_v_pb2 import Pose_V
        from gz.transport13 import Node
        from gz.msgs10.clock_pb2 import Clock
        self.projector=ObjectProjector(calibration,clock_domain)
        self._lock=Lock();self._pending=None;self._closed=False
        self.clock_bridge=GazeboClockBridge()
        self.node=Node();self.topic=f'/world/{calibration.world}/pose/info'
        if not self.node.subscribe(Pose_V,self.topic,self._receive):raise RuntimeError('object subscription failed')

        self.clock_topic=f'/world/{calibration.world}/clock'
        if not self.node.subscribe(Clock,self.clock_topic,self._clock):raise RuntimeError('simulation clock subscription failed')

    def _clock(self,message):
        received=time.monotonic_ns()
        sim=message.sim.sec*1_000_000_000+message.sim.nsec
        real=message.real.sec*1_000_000_000+message.real.nsec
        with self._lock:self.clock_bridge.ingest(sim,real,received)

    def _receive(self,message):
        now=time.monotonic_ns();stamp=message.header.stamp
        positions={p.name:Vector3(p.position.x,p.position.y,p.position.z) for p in message.pose if p.name in self.projector.calibration.models}
        with self._lock:
            if not self._closed:self._pending=(stamp.sec*1_000_000_000+stamp.nsec,now,positions)

    def poll(self,now):
        with self._lock:
            if self.clock_bridge.error:
                if self.projector.error:return ()
                self.projector.error=self.clock_bridge.error
                return self.projector.invalidate(now.monotonic_ns)
            packet=self._pending
            if packet is None:return ()
            capture=self.clock_bridge.capture(packet[0])
            if capture is None:return ()
            self._pending=None
        return self.projector.project(*packet,capture_ns=capture)

    def close(self):
        with self._lock:self._closed=True;self._pending=None
        self.node.unsubscribe(self.topic);self.node.unsubscribe(self.clock_topic)
