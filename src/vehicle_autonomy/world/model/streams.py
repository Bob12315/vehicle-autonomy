"""Bounded current stream state, separate from high-rate payload storage.

Generation changes require trusted explicit registration. Packet receipt cannot
refresh old capture facts; replay and test truth never qualify live navigation.
"""
from dataclasses import dataclass
from threading import RLock

from vehicle_autonomy.contracts.streams import StreamObservation,DataKind,SourceKind,FrameDescriptor,identity
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.core.time import TimePoint


@dataclass(frozen=True, slots=True)
class StreamProfile:
    source_id: str
    sensor_id: str
    kind: DataKind
    generation: str
    frame: FrameDescriptor
    calibration_version: str
    source_kind: SourceKind
    max_age_ns: int
    min_confidence: float=0.

    def __post_init__(self):
        for v,n in ((self.source_id,'source'),(self.sensor_id,'sensor'),(self.generation,'generation'),(self.calibration_version,'calibration')):identity(v,n)
        if not isinstance(self.kind,DataKind) or not isinstance(self.source_kind,SourceKind) or not isinstance(self.frame,FrameDescriptor):raise TypeError('typed stream profile required')
        if type(self.max_age_ns) is not int or not 1<=self.max_age_ns<=60_000_000_000:raise ValueError('bounded source age required')
        if type(self.min_confidence) not in (int,float) or not 0<=self.min_confidence<=1:raise ValueError('bounded confidence required')


class StreamState:
    def __init__(self,*,capacity=64):
        if type(capacity) is not int or not 1<=capacity<=256:raise ValueError('bounded stream capacity required')
        self.capacity=capacity;self._lock=RLock();self._profiles={};self._latest={};self._sequences={}
        self.accepted=0;self.dropped=0

    @staticmethod
    def key(source_id,sensor_id,kind):return source_id,sensor_id,kind

    def register(self,profile):
        """Trusted composition only. No implicit discovery or epoch replacement."""
        if not isinstance(profile,StreamProfile):raise TypeError('typed source profile required')
        key=self.key(profile.source_id,profile.sensor_id,profile.kind)
        with self._lock:
            if key in self._profiles:raise ValueError('stream already registered; use a new deployment for a new epoch')
            if len(self._profiles)>=self.capacity:raise ValueError('stream capacity exhausted')
            self._profiles[key]=profile

    def ingest(self,observation):
        if not isinstance(observation,StreamObservation):raise TypeError('typed observation required')
        h=observation.header;key=self.key(h.source_id,h.sensor_id,h.kind)
        with self._lock:
            p=self._profiles.get(key)
            if p is None or (h.generation,h.frame,h.calibration_version,h.source_kind)!=(p.generation,p.frame,p.calibration_version,p.source_kind):
                self.dropped+=1;raise ValueError('stream identity/frame/calibration/source epoch mismatch')
            previous=self._latest.get(key)
            if h.sequence<=self._sequences.get(key,-1):
                self.dropped+=1
                if previous==observation:return False
                raise ValueError('duplicate or regressed source sequence')
            if previous:
                old=previous.header
                if h.source_clock_domain!=old.source_clock_domain or h.source_timestamp_ns<=old.source_timestamp_ns:
                    self.dropped+=1;raise ValueError('source time did not advance; explicit fresh epoch required')
                if h.received_at.clock_domain_id!=old.received_at.clock_domain_id or h.received_at<old.received_at:
                    self.dropped+=1;raise ValueError('receipt clock changed or regressed')
            self._latest[key]=observation;self._sequences[key]=h.sequence;self.accepted+=1
            return True

    def ingest_many(self,observations):
        if not isinstance(observations,tuple) or len(observations)>self.capacity:raise ValueError('bounded immutable stream batch required')
        with self._lock:
            latest=dict(self._latest);sequences=dict(self._sequences);accepted=self.accepted
            try:
                keys=[self.key(s.header.source_id,s.header.sensor_id,s.header.kind) for s in observations]
                if len(set(keys))!=len(keys):raise ValueError('one observation per stream in an atomic cut')
                for sample in observations:self.ingest(sample)
            except Exception:
                self._latest=latest;self._sequences=sequences;self.accepted=accepted
                raise

    def withdraw(self,source_id):
        """A lost worker invalidates references without resetting replay fences."""
        with self._lock:
            for key in tuple(self._latest):
                if key[0]==source_id:self._latest.pop(key)

    def snapshot(self,now,*,navigation=False):
        if not isinstance(now,TimePoint):raise TypeError('typed current time required')
        with self._lock:
            rows=[]
            for key,p in self._profiles.items():
                sample=self._latest.get(key);reason=None;age=None
                if sample is None:reason='unavailable'
                else:
                    h=sample.header
                    if h.captured_at is None:reason='capture_time_unqualified'
                    elif h.captured_at.clock_domain_id!=now.clock_domain_id or h.received_at.clock_domain_id!=now.clock_domain_id:reason='clock_domain_mismatch'
                    else:
                        ages=(now.monotonic_ns-h.captured_at.monotonic_ns,now.monotonic_ns-h.received_at.monotonic_ns)
                        if min(ages)<0:reason='future_timestamp'
                        else:
                            age=max(ages)
                            if age>p.max_age_ns:reason='expired'
                    if reason is None and (h.quality is not QualityState.VALID or h.confidence<p.min_confidence):reason='insufficient_quality'
                    if navigation and h.source_kind in (SourceKind.REPLAY,SourceKind.TEST_TRUTH):reason='not_live_navigation_evidence'
                rows.append(dict(profile=p,sample=sample if reason is None else None,usable=reason is None,reason=reason,age_ns=age))
            return tuple(rows)

    def require(self,now,requirements):
        """Return qualified references only, never grant SEND or localization."""
        rows={self.key(r['profile'].source_id,r['profile'].sensor_id,r['profile'].kind):r for r in self.snapshot(now,navigation=True)}
        result=[]
        for key in requirements:
            row=rows.get(key)
            if row is None or not row['usable']:raise ValueError('navigation input unavailable: '+str(key)+': '+str(None if row is None else row['reason']))
            result.append(row['sample'])
        return tuple(result)
