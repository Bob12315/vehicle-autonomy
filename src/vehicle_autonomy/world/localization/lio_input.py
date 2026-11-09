"""Typed, read-only LIO World Model; never selects the vehicle control source."""
from datetime import datetime,timezone,timedelta
import json,math,time,os,stat
from pathlib import Path

from vehicle_autonomy.contracts.core.geometry import Pose3,Quaternion,Vector3,Twist3
from vehicle_autonomy.contracts.core.primitives import SchemaVersion,ResourceVersion
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.core.stamped import Stamped
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.localization.models import LocalizationEstimate
from vehicle_autonomy.contracts.world.models import ResourceReference
from vehicle_autonomy.world.model.service import WorldModel,FreshnessLimits


def at(value):
    return TimePoint(value,datetime.now(timezone.utc)-timedelta(microseconds=(time.monotonic_ns()-value)//1000),'host-monotonic-simulation')


class LioWorldSource:
    def __init__(self,directory,generation,frame_id,*,max_age_ns=1_000_000_000,producer='fast-lio2'):
        self.directory=Path(directory).absolute();self.generation=generation;self.frame_id=frame_id;self.max_age_ns=max_age_ns
        if self.directory.resolve()!=self.directory:raise ValueError('real owned LIO directory required')
        info=self.directory.stat();self.directory_identity=(info.st_dev,info.st_ino)
        self.model=WorldModel(generation,FreshnessLimits(max_age_ns,max_age_ns,max_age_ns))
        self.last=None;self.latched=None;self.error='waiting for LIO';self.raw=None
        self.producer=producer
        self.last_map=None

    def update(self,*,owner_running,now=None):
        supplied_now=now is not None
        now=at(time.monotonic_ns()) if now is None else now
        try:
            if not owner_running:raise ValueError('LIO owner stopped')
            if self.directory.resolve()!=self.directory:raise ValueError('LIO directory changed')
            directory_fd=os.open(self.directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                info=os.fstat(directory_fd)
                if (info.st_dev,info.st_ino)!=self.directory_identity:raise ValueError('LIO directory identity changed')
                fd=os.open('state.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory_fd)
            finally:os.close(directory_fd)
            try:
                info=os.fstat(fd)
                # Atomic replacement can unlink the exact regular file we
                # just opened; that owned descriptor remains a valid snapshot.
                # Multiple links are still rejected, as are symlinks/devices.
                if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink not in (0,1) or info.st_size>131072:raise ValueError('invalid LIO exchange file')
                data=os.read(fd,131073)
                if len(data)>131072:raise ValueError('LIO exchange file grew')
            finally:os.close(fd)
            raw=json.loads(data)
            if not isinstance(raw,dict):raise ValueError('invalid LIO state document')
            # An atomic publication may replace the file after this call began.
            # Validate against observation completion, never an earlier read
            # start. Source capture/publication timestamps stay unchanged.
            if not supplied_now:now=at(time.monotonic_ns())
            self.raw=raw
            if self.latched:raise ValueError(self.latched)
            if raw.get('generation')!=self.generation or raw.get('frame_id')!=self.frame_id:
                self.latched='LIO generation/frame changed';raise ValueError(self.latched)
            if not raw.get('online'):raise ValueError(raw.get('error') or 'LIO unavailable')
            pose=raw['localization'];capture=pose['captured_host_ns'];publication=pose['published_host_ns']
            if any(type(v) is not int or not 0<=now.monotonic_ns-v<=self.max_age_ns for v in (capture,publication,raw['published_host_ns'])):
                raise ValueError('LIO source expired or future timestamp')
            if capture>publication:raise ValueError('LIO capture follows publication')
            values=pose['position']+pose['quaternion']
            if len(values)!=7 or not all(type(v) in (int,float) and math.isfinite(v) for v in values):raise ValueError('invalid LIO pose')
            if abs(sum(v*v for v in pose['quaternion'])-1)>.001:raise ValueError('invalid LIO orientation norm')
            cut=(raw['revision'],pose['capture_ros_ns'],tuple(values),capture,publication)
            if self.last and (cut[0]<self.last[0] or cut[1]<self.last[1] or cut[0]==self.last[0] and cut!=self.last):
                self.latched='LIO source cut regressed/reused';raise ValueError(self.latched)
            value=Pose3(Vector3(*pose['position']),Quaternion(*pose['quaternion']))
            twist=None
            if pose.get('derived_twist'):
                t=pose['derived_twist'];twist=Stamped(self.frame_id,at(capture),Twist3(Vector3(*t['linear']),Vector3(*t['angular'])))
            estimate=LocalizationEstimate(SchemaVersion(1,0),ResourceVersion(self.generation,raw['revision']),
                self.producer+':'+self.generation,at(publication),Stamped(self.frame_id,at(capture),value),QualityState.DEGRADED,twist=twist,covariance=None)
            self.model.update_localization(estimate);self.last=cut;self.error=None
            if raw.get('map_reference') and not raw.get('map',{}).get('error'):
                revision=raw['map_export_revision'];captured=raw['map_export_capture_host_ns']
                if type(revision) is not int or revision<1 or type(captured) is not int or not 0<=now.monotonic_ns-captured<=10_000_000_000:
                    self.model.update_map(None)
                else:
                    map_cut=(revision,captured,raw['map_reference']['sha256'])
                    if self.last_map and (revision<self.last_map[0] or revision==self.last_map[0] and map_cut!=self.last_map):
                        self.latched='map resource cut regressed/reused';raise ValueError(self.latched)
                    self.model.update_map(ResourceReference('lio-map3d:'+self.generation,ResourceVersion(self.generation,revision)),at(captured));self.last_map=map_cut
            else:self.model.update_map(None)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.error=str(exc);self.model.update_localization(None);self.model.update_map(None)
        return self.model.publish(now)

    def reader(self):return self.model.reader()
