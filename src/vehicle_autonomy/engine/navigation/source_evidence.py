"""Original controller evidence, independent of final smoother timestamps.

Caller is the owned authenticated ROS receiver. This class grants no authority.
MAVLink packet sequence and local receipt counters are not request identifiers.
"""
from dataclasses import dataclass
from collections import OrderedDict
import math
from threading import RLock
from vehicle_autonomy.contracts.core.time import TimePoint


@dataclass(frozen=True,slots=True)
class ControllerStamp:
    source_stamp_ns: int
    captured_at: TimePoint
    received_at: TimePoint
    twist: tuple[float,...]

    def __post_init__(self):
        if type(self.source_stamp_ns) is not int or self.source_stamp_ns<=0:raise ValueError('actual nonzero original controller stamp required')
        if not isinstance(self.captured_at,TimePoint) or not isinstance(self.received_at,TimePoint):raise TypeError('qualified controller timestamps required')
        if not isinstance(self.twist,tuple) or len(self.twist)!=6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in self.twist):raise ValueError('finite full source Twist required')
        if any(abs(self.twist[i])>1e-9 for i in (1,2,3,4)):raise ValueError('Rover source requires FLU planar Twist')


class ControllerEvidence:
    MAX_AGE_NS=200_000_000
    def __init__(self,opened_at,*,capacity=16):
        if not isinstance(opened_at,TimePoint) or type(capacity) is not int or not 4<=capacity<=64:raise ValueError('bounded explicitly admitted source window required')
        self.opened_at=opened_at;self.capacity=capacity;self._samples=OrderedDict();self._lock=RLock();self.closed=False
        self.accepted=0;self.duplicates=0;self.ambiguous=0
    def _time(self,fact,now):
        if self.closed:raise ValueError('navigation source window closed')
        if any(t.clock_domain_id!=self.opened_at.clock_domain_id for t in (fact.captured_at,fact.received_at,now)):raise ValueError('controller evidence clock mismatch')
        if not self.opened_at.monotonic_ns<=fact.captured_at.monotonic_ns<=fact.received_at.monotonic_ns<=now.monotonic_ns:raise ValueError('controller evidence admission/receipt chronology')
        if now.monotonic_ns-fact.captured_at.monotonic_ns>=self.MAX_AGE_NS:raise ValueError('original controller source expired')
    def record(self,fact,now):
        if not isinstance(fact,ControllerStamp):raise TypeError('typed original controller fact required')
        with self._lock:
            self._time(fact,now);key=fact.source_stamp_ns
            if key in self._samples:
                old=self._samples[key]
                if old is None or old.twist!=fact.twist:
                    self._samples[key]=None;self.ambiguous+=1;return False
                # Preserve FIRST source capture and receipt. A repeated callback
                # cannot refresh either, even if its newly mapped clock differs.
                self.duplicates+=1;return False
            self._samples[key]=fact;self.accepted+=1
            while len(self._samples)>self.capacity:
                oldest=min(self._samples);self._samples.pop(oldest)
            return True
    def original(self,final_stamp_ns,now):
        with self._lock:
            fact=self._samples.get(final_stamp_ns)
            if fact is None:raise ValueError('final output lacks unambiguous original controller evidence')
            self._time(fact,now);return fact
    def close(self):
        with self._lock:self.closed=True;self._samples.clear()
