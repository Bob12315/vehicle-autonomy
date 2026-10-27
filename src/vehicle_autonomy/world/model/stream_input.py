"""Same-host owned worker references -> existing WorldModel, no payload copying."""
from datetime import datetime
import json
import os
from pathlib import Path
import stat

from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.streams import SourceKind,DataKind,FrameDescriptor,SampleHeader,DataReference,StreamObservation
from vehicle_autonomy.world.model.streams import StreamProfile


def timepoint(value):
    if value is None:return None
    if type(value) is not dict or set(value)!={'monotonic_ns','utc','clock_domain_id'}:raise ValueError('strict original timestamp required')
    return TimePoint(value['monotonic_ns'],datetime.fromisoformat(value['utc']),value['clock_domain_id'])


def observation(value):
    if type(value) is not dict or not {'header','data'}<=value.keys() or value.keys()-{'header','data','layout'}:raise ValueError('strict worker observation required')
    h=dict(value['header']);h['kind']=DataKind(h['kind']);h['source_kind']=SourceKind(h['source_kind']);h['quality']=QualityState(h['quality'])
    h['frame']=FrameDescriptor(**h['frame']);h['received_at']=timepoint(h['received_at']);h['captured_at']=timepoint(h['captured_at']);h['covariance']=tuple(h['covariance'])
    d=dict(value['data']);d['dimensions']=tuple(d['dimensions'])
    return StreamObservation(SampleHeader(**h),DataReference(**d))


class WorkerStreamInput:
    def __init__(self,model,directory,*,source_id,origin_id,calibration_version,frames,max_age_ns=500_000_000):
        self.model=model;self.root=Path(directory).absolute();self.source_id=source_id;self.origin_id=origin_id;self.calibration=calibration_version
        if self.root.resolve()!=self.root:raise ValueError('real owned worker root required')
        info=self.root.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077:raise ValueError('private owned worker root required')
        self.identity=(info.st_dev,info.st_ino);self.frames=dict(frames);self.max_age=max_age_ns;self.generation=None;self.registered=set();self.last_seen={};self.error=None
    def poll(self,now,*,clock=None):
        try:
            info=self.root.stat()
            if self.root.resolve()!=self.root or (info.st_dev,info.st_ino)!=self.identity:raise ValueError('worker directory identity changed')
            fd=os.open(self.root/'state.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            try:
                info=os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_size>262144:raise ValueError('worker metadata budget/ownership')
                with os.fdopen(fd,'rb',closefd=False) as f:raw=f.read(262145)
                if len(raw)>262144:raise ValueError('worker metadata budget')
                data=json.loads(raw)
            finally:os.close(fd)
            # Metadata can be atomically published AFTER the poll began.
            # Check freshness against a post-read time; never rewrite sample
            # capture/receipt facts or tolerate a genuinely future producer.
            if clock is not None:
                checked=clock()
                if not isinstance(checked,TimePoint) or checked.elapsed_ns_since(now)<0:raise ValueError('reader clock regressed')
                now=checked
            if data['schema']!=1 or data['source_id']!=self.source_id or data['source_kind']!='simulation' or data['origin_id']!=self.origin_id or data['ap_world_epoch']!=self.origin_id:
                raise ValueError('worker source or AP frame epoch mismatch')
            if data['error'] is not None:raise ValueError('worker unavailable: '+str(data['error'])[:256])
            if not 0<=now.monotonic_ns-data['published_ns']<=500_000_000:raise ValueError('worker heartbeat stale/future: age_ns='+str(now.monotonic_ns-data['published_ns']))
            if self.generation is not None and data['generation']!=self.generation:raise ValueError('worker restarted; source readmission required')
            if set(data['streams'])-self.frames.keys():raise ValueError('unknown worker streams')
            candidates=[]
            for name,raw in data['streams'].items():
                item=observation(raw);h=item.header
                if (h.source_id,h.sensor_id,h.generation,h.calibration_version,h.frame,h.source_kind)!=(self.source_id,name,data['generation'],self.calibration,self.frames[name],SourceKind.SIMULATION):
                    raise ValueError('stream profile does not attest actual source/frame/calibration')
                old=self.last_seen.get(name)
                if old is not None and h.sequence<=old.header.sequence:
                    if item!=old:raise ValueError('worker observation replay/conflicting duplicate')
                    continue # Same original fact cannot reappear after withdrawal.
                candidates.append(item)
            # Validate the complete worker cut before adopting any input.
            for item in candidates:
                h=item.header
                if h.sensor_id not in self.registered:
                    self.model.register_stream(StreamProfile(h.source_id,h.sensor_id,h.kind,h.generation,h.frame,h.calibration_version,h.source_kind,self.max_age[h.sensor_id] if isinstance(self.max_age,dict) else self.max_age))
                    self.registered.add(h.sensor_id)
            self.model.ingest_streams(tuple(candidates))
            for item in candidates:self.last_seen[item.header.sensor_id]=item
            self.generation=data['generation'];self.error=None
            return True
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.error=type(exc).__name__+': '+str(exc)
            self.model.withdraw_streams(self.source_id)
            return False
