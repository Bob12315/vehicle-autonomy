"""Bounded Phase 5 event ingress; unchanged Phase 4 cursor/read protocol.

Source watermarks survive event eviction. An overrun is explicit, never silently
relabelled as a new subscription. No motion capability is granted here.
"""
from collections import deque
import hashlib
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.mission import BlackboardValue
from vehicle_autonomy.contracts.streams import DataKind,SourceKind,StreamObservation
from vehicle_autonomy.world.model.streams import StreamProfile
from vehicle_autonomy.world.model.mission_inputs import LocalEvents,MissionEvent,usable


class ObservationEvents(LocalEvents):
    def __init__(self,limit=2048):
        super().__init__(limit);self._events=deque();self._sequence=0;self.evicted_through=0;self._sources={};self._last={};self._emitted={};self._presence={};self._degraded=set()
        self.accepted_frames=0;self.duplicate_frames=0;self.dropped_events=0
    @property
    def cursor(self):
        with self._lock:return self._sequence
    def register(self,profile):
        if not isinstance(profile,StreamProfile) or profile.kind is not DataKind.DETECTIONS or profile.source_kind not in (SourceKind.LIVE,SourceKind.SIMULATION):raise ValueError('qualified live detection profile required')
        key=(profile.source_id,profile.sensor_id)
        with self._lock:
            if key in self._sources and self._sources[key]!=profile:raise ValueError('event source epoch replacement requires explicit new deployment')
            if key not in self._sources and len(self._sources)>=64:raise ValueError('event source capacity exhausted')
            self._sources[key]=profile
    def _append(self,identifier,name,value,at,ttl_ns,frame=None,quality='VALID',source='explicit-event-source'):
        if len(self._events)>=self.limit:
            self.evicted_through=self._events.popleft().sequence;self.dropped_events+=1
        self._sequence+=1;data=BlackboardValue(value,at,ttl_ns,quality,frame,source)
        self._events.append(MissionEvent(self._sequence,identifier,name,data));return True
    def publish(self,identifier,name,value,now,*,ttl_s=5,quality='VALID',frame=None):
        if not all(isinstance(s,str) and 0<len(s)<=128 for s in (identifier,name)) or type(ttl_s) not in (int,float) or not 0<ttl_s<=60:raise ValueError('bounded explicit event required')
        with self._lock:
            if identifier in self._ids:return False
            if len(self._ids)>=self.limit:raise ValueError('explicit event identity budget exhausted; controlled epoch renewal required')
            self._ids.add(identifier);return self._append(identifier,name,value,now,int(ttl_s*1e9),frame,quality)
    def publish_observation(self,item,value,now):
        if not isinstance(item,StreamObservation):raise TypeError('typed actual detection reference required')
        h=item.header;key=(h.source_id,h.sensor_id)
        with self._lock:
            p=self._sources.get(key)
            if p is None or (h.generation,h.kind,h.source_kind,h.frame,h.calibration_version)!=(p.generation,p.kind,p.source_kind,p.frame,p.calibration_version):raise ValueError('event source profile mismatch')
            if h.quality is not QualityState.VALID or h.captured_at is None or not 0<=now.elapsed_ns_since(h.captured_at)<p.max_age_ns:raise ValueError('event source invalid/expired')
            previous=self._last.get(key)
            if previous:
                old=previous.header
                if h.sequence<=old.sequence:
                    if item==previous:self.duplicate_frames+=1;return False
                    raise ValueError('event source replay/conflict')
                if h.source_clock_domain!=old.source_clock_domain or h.source_timestamp_ns<=old.source_timestamp_ns or h.captured_at<old.captured_at:raise ValueError('event source time regression')
            if type(value) is not dict or type(value.get('detected')) is not bool or type(value.get('detections')) is not list or len(value['detections'])>128:raise ValueError('bounded actual detection payload required')
            self._last[key]=item;self.accepted_frames+=1;self._degraded.discard(key)
            present=value['detected'];was=self._presence.get(key,False);self._presence[key]=present
            # Current object queries stay full rate. Detection notifications are
            # at most 1 Hz per producer, with immediate appearance/loss edges.
            if not present and not was:return False
            last=self._emitted.get(key)
            if present==was and last is not None and h.captured_at.monotonic_ns-last<1_000_000_000:return False
            self._emitted[key]=h.captured_at.monotonic_ns
            name='object.detected' if present else 'object.lost'
            identifier=hashlib.sha256((h.source_id+h.generation+str(h.sequence)+name).encode()).hexdigest()
            payload=dict(value,source_id=h.source_id,generation=h.generation,sequence=h.sequence,captured_at=to_json_value(h.captured_at),frame_id=h.frame.frame_id)
            return self._append(identifier,name,payload,h.captured_at,p.max_age_ns,h.frame.frame_id,source='world:'+h.source_id)
    def degraded(self,source_id,sensor_id,now,reason):
        key=source_id,sensor_id
        with self._lock:
            if key not in self._sources or key in self._degraded:return False
            self._degraded.add(key)
            identifier=hashlib.sha256((source_id+str(now.monotonic_ns)+'degraded').encode()).hexdigest()
            return self._append(identifier,'perception.degraded',dict(source_id=source_id,reason=reason,component_quality='UNKNOWN'),now,2_000_000_000,source='world-health:'+source_id)
    def read(self,after,name,now):
        with self._lock:
            if after<self.evicted_through:raise ValueError('event cursor overrun; event outcome UNKNOWN')
            return tuple(e for e in self._events if e.sequence>after and e.name==name and usable(e.data,now))
