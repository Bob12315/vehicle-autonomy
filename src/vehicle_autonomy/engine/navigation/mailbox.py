"""One pinned final producer, one Action/goal/session, one current command.

This is a same-host input fence, not DDS authentication or vehicle authority.
Only an explicitly composed receiver may submit validated final-chain samples.
"""
from dataclasses import dataclass
import math
from threading import RLock

from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.streams import identity


@dataclass(frozen=True,slots=True)
class NavigationBinding:
    action_id: str
    target_id: str
    provider_id: str
    provider_epoch: str
    vehicle_session: str
    world_generation: str
    goal_id: str
    producer_gid: str
    clock_domain: str
    frame_id: str='base_link'

    def __post_init__(self):
        for name in self.__dataclass_fields__:identity(getattr(self,name),name)
        if self.frame_id!='base_link':raise ValueError('Rover bridge requires base_link FLU')
        if len(self.producer_gid) not in (32,48) or any(v not in '0123456789abcdef' for v in self.producer_gid) or set(self.producer_gid)=={'0'}:
            raise ValueError('actual pinned final publisher GID required')


@dataclass(frozen=True,slots=True)
class NavigationCommand:
    binding: NavigationBinding
    sequence: int
    source_stamp_ns: int
    captured_at: TimePoint
    received_at: TimePoint
    speed_mps: float
    yaw_rate_rad_s: float

    def __post_init__(self):
        if not isinstance(self.binding,NavigationBinding):raise TypeError('typed goal binding required')
        if any(type(x) is not int or x<0 for x in (self.sequence,self.source_stamp_ns)):raise ValueError('source sequence/time required')
        if not isinstance(self.captured_at,TimePoint) or not isinstance(self.received_at,TimePoint):raise TypeError('original source and receipt times required')
        if any(type(v) not in (float,int) or not math.isfinite(v) for v in (self.speed_mps,self.yaw_rate_rad_s)):raise ValueError('finite commands required')


class NavigationMailbox:
    MAX_AGE_NS=200_000_000
    def __init__(self,binding,opened_at):
        if not isinstance(binding,NavigationBinding):raise TypeError('explicit immutable bridge binding required')
        if not isinstance(opened_at,TimePoint) or opened_at.clock_domain_id!=binding.clock_domain:raise TypeError('bridge admission clock required')
        self.opened_at=opened_at;self.binding=binding;self._lock=RLock();self._last=None;self._closed=False;self.accepted=0;self.rejected=0
    def _valid(self,c,now):
        if self._closed or c.binding!=self.binding:raise ValueError('inactive or mismatched navigation goal')
        if any(t.clock_domain_id!=self.binding.clock_domain for t in (now,c.captured_at,c.received_at)):raise ValueError('bridge clock mismatch')
        if c.captured_at.monotonic_ns<self.opened_at.monotonic_ns:raise ValueError('command predates navigation admission')
        if not 0<=now.monotonic_ns-c.captured_at.monotonic_ns<self.MAX_AGE_NS:raise ValueError('navigation source expired/future')
        if not c.captured_at.monotonic_ns<=c.received_at.monotonic_ns<=now.monotonic_ns:raise ValueError('bridge receive chronology')
        if abs(c.speed_mps)>.5 or abs(c.yaw_rate_rad_s)>.35:raise ValueError('Rover existing speed/yaw limits')
    def accept(self,command,now):
        if not isinstance(command,NavigationCommand) or not isinstance(now,TimePoint):raise TypeError('typed navigation input required')
        with self._lock:
            try:
                self._valid(command,now)
                old=self._last
                if old is not None:
                    if command.sequence<=old.sequence or command.source_stamp_ns<=old.source_stamp_ns or command.captured_at.monotonic_ns<=old.captured_at.monotonic_ns:
                        raise ValueError('duplicate/reordered source cannot renew deadman')
                    dt=(command.source_stamp_ns-old.source_stamp_ns)/1e9
                    for new,previous,rate in ((command.speed_mps,old.speed_mps,.3),(command.yaw_rate_rad_s,old.yaw_rate_rad_s,.5)):
                        # Emergency reductions toward zero are never delayed.
                        reducing=new*previous>=0 and abs(new)<=abs(previous)
                        if not reducing and abs(new-previous)>rate*dt+1e-6:raise ValueError('navigation acceleration limit')
                else:
                    dt=min(self.MAX_AGE_NS,command.captured_at.monotonic_ns-self.opened_at.monotonic_ns)/1e9
                    if abs(command.speed_mps)>.3*dt+1e-6 or abs(command.yaw_rate_rad_s)>.5*dt+1e-6:
                        raise ValueError('first command must ramp from admitted stationary state')
                self._last=command;self.accepted+=1
            except Exception:self.rejected+=1;raise
    def latest(self,now):
        with self._lock:
            if self._last is None:raise ValueError('no qualified final navigation command')
            self._valid(self._last,now)
            return self._last
    def close(self):
        with self._lock:self._closed=True;self._last=None
