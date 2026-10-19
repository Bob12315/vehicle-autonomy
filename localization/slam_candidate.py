"""Read-only SLAM pose candidate/quality audit beside the active telemetry source.

Map-time poses have no independent high-rate twist and are NOT control-ready.
Switching the execution source requires a separate localization/guard contract.
"""
from dataclasses import dataclass
import math
from contracts.core.geometry import Pose3
from contracts.core.time import TimePoint
from contracts.core.quality import QualityState
from guidance.path_following import angle
from mapping.grid import pose_from_json


def yaw(pose):
    q=pose.orientation
    return math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))


@dataclass(frozen=True,slots=True)
class SlamPoseCandidate:
    pose: Pose3
    captured_at: TimePoint
    frame_epoch: str
    source_generation: str
    revision: int
    quality: QualityState


class SlamCandidateAudit:
    def __init__(self):
        self.identity=None
        self.alignment=None
        self.candidate=None
        self.error='no_slam_candidate'
        self.latched=False
        self.last_cut=None

    def reset(self,*,armed,system_send,action_send):
        if armed or system_send or action_send:raise ValueError('localization reset requires disarmed SEND-disabled idle')
        self.__init__()

    def update(self,context,health,now,frame_epoch):
        self.candidate=None
        if self.latched:return
        try:
            if context is None or not health.get('valid'):raise ValueError('slam_candidate_unavailable')
            context.check_fresh(now)
            identity=(str(frame_epoch),str(context.reference.version.generation_id))
            if (str(context.frame_epoch)!=str(frame_epoch) or health['source_epoch']!=identity[1]
                    or health['frame_epoch']!=identity[0] or health['frame']!='map'
                    or health['captured_ns']!=context.captured_at.monotonic_ns
                    or health['revision']!=context.reference.version.revision):
                raise ValueError('slam_candidate_epoch_mismatch')
            if self.identity is not None and self.identity!=identity:
                self.latched=True;raise ValueError('slam_candidate_source_switch_requires_reset')
            alignment=pose_from_json(health['odom_in_map'])
            if self.alignment is not None and (math.hypot(alignment.position.x-self.alignment.position.x,
                    alignment.position.y-self.alignment.position.y)>.15 or abs(angle(yaw(alignment)-yaw(self.alignment)))>.1):
                self.latched=True;raise ValueError('slam_candidate_relocalization_jump')
            pose=pose_from_json(health['base_link_in_map'])
            if abs(pose.orientation.x)>.01 or abs(pose.orientation.y)>.01:raise ValueError('slam_candidate_nonplanar')
            cut=(context.reference.version.revision,context.captured_at.monotonic_ns,context.sha256,pose,alignment)
            if self.last_cut is not None and (cut[0]<self.last_cut[0] or cut[1]<self.last_cut[1]
                    or (cut[0]==self.last_cut[0] and cut!=self.last_cut)):
                self.latched=True;raise ValueError('slam_candidate_cut_regressed_or_reused')
            self.identity,self.alignment=identity,alignment
            self.last_cut=cut
            age=now.elapsed_ns_since(context.captured_at)
            quality=QualityState.VALID if age<=500_000_000 else QualityState.DEGRADED
            self.candidate=SlamPoseCandidate(pose,context.captured_at,*identity,context.reference.version.revision,quality)
            self.error=None
        except (ValueError,TypeError,KeyError) as exc:self.error=str(exc)

    def view(self,now):
        c=self.candidate
        return {'active_source':'vehicle_reported_odom','candidate_source':'ros2.slam_toolbox.map_tf',
            'control_eligible':False,'reason':'map-rate pose has no independently validated twist/source-switch contract',
            'error':self.error,'latched':self.latched,'candidate':None if c is None else {
                'frame':'map','frame_epoch':c.frame_epoch,'source_generation':c.source_generation,'revision':c.revision,
                'quality':c.quality.value,'captured_ns':c.captured_at.monotonic_ns,
                'age_ns':now.elapsed_ns_since(c.captured_at),'position':[c.pose.position.x,c.pose.position.y,c.pose.position.z]}}
