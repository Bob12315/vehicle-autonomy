"""Persistent map coordinates require an explicit Environment/session binding.

An exported grid is not a localization authority. A saved anchor is deliberately
rejected after either publisher or vehicle restarts; re-registration is explicit.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import os
import stat
from pathlib import Path

from guidance.path_following import PlanarBinding,angle
from mapping.grid import atomic_json


@dataclass(frozen=True,slots=True)
class MapAnchor:
    environment_id: str
    environment_sha256: str
    frame_epoch: str
    source_generation: str
    map_sha256: str
    revision: int
    binding: PlanarBinding
    home_name: str
    home_odom: tuple[float,float,float]

    @classmethod
    def create(cls,environment,context,binding,now,vehicle,*,system_send,action_send):
        context.check_fresh(now)
        environment.validate_origin(vehicle)
        if vehicle.operation.armed or system_send or action_send:
            raise ValueError('map registration requires disarmed SEND-disabled idle')
        if vehicle.reported_pose is None or vehicle.reported_pose.frame_id!='odom' or not 0<=now.elapsed_ns_since(vehicle.reported_pose.captured_at)<=500_000_000:
            raise ValueError('map registration requires fresh odom pose')
        twist=vehicle.reported_twist
        if twist is None or not 0 <= now.elapsed_ns_since(twist.captured_at) <= 500_000_000 or (
                math.hypot(twist.value.linear.x,twist.value.linear.y)>.1 or abs(twist.value.angular.z)>.15):
            raise ValueError('map registration requires observed stationary state')
        if context.source_kind!='live_map' or environment.frame_epoch!=context.frame_epoch:
            raise ValueError('fresh same-session live map and verified Environment required')
        home=environment.home().position
        return cls(str(environment.resource_id),environment.content_hash,str(context.frame_epoch),
            str(context.reference.version.generation_id),context.sha256,context.reference.version.revision,
            binding,environment.home_name,(home.x,home.y,home.z))

    def document(self):
        return {'schema':1,'environment_id':self.environment_id,'environment_sha256':self.environment_sha256,
            'frame_epoch':self.frame_epoch,'source_generation':self.source_generation,'map_sha256':self.map_sha256,
            'revision':self.revision,'binding':[self.binding.x,self.binding.y,self.binding.yaw],
            'home_name':self.home_name,'home_odom':list(self.home_odom)}

    def save(self,path):atomic_json(Path(path),self.document())

    @classmethod
    def load(cls,path):
        return cls.load_with_sha(path)[0]

    @classmethod
    def load_with_sha(cls,path):
        fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>8192:raise ValueError('bounded regular map anchor required')
            raw=stream.read(8193)
        if len(raw)>8192:raise ValueError('map anchor exceeds size bound')
        d=json.loads(raw)
        fields={'schema','environment_id','environment_sha256','frame_epoch','source_generation','map_sha256',
                'revision','binding','home_name','home_odom'}
        if type(d) is not dict or set(d)!=fields or type(d['schema']) is not int or d['schema']!=1:
            raise ValueError('invalid map anchor schema')
        for key in ('environment_id','frame_epoch','source_generation','home_name'):
            if type(d[key]) is not str or not d[key]:raise ValueError('map anchor identity required')
        for key in ('environment_sha256','map_sha256'):
            if type(d[key]) is not str or len(d[key])!=64 or any(c not in '0123456789abcdef' for c in d[key]):
                raise ValueError('invalid map anchor content identity')
        if type(d['revision']) is not int or d['revision']<0:raise ValueError('invalid map anchor revision')
        for key in ('binding','home_odom'):
            if type(d[key]) is not list or len(d[key])!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in d[key]):
                raise ValueError('map anchor requires finite planar SI values')
        return (cls(d['environment_id'],d['environment_sha256'],d['frame_epoch'],d['source_generation'],
            d['map_sha256'],d['revision'],PlanarBinding(*d['binding']),d['home_name'],tuple(d['home_odom'])),
            hashlib.sha256(raw).hexdigest())

    def check(self,environment,context,binding,now):
        context.check_fresh(now)
        if context.source_kind!='live_map':raise ValueError('map_anchor_requires_live_session')
        home=environment.home().position
        if (str(environment.resource_id),environment.content_hash,environment.home_name,(home.x,home.y,home.z)) != (
                self.environment_id,self.environment_sha256,self.home_name,self.home_odom):
            raise ValueError('map_anchor_environment_or_home_changed')
        if str(context.frame_epoch)!=self.frame_epoch or environment.frame_epoch!=self.frame_epoch:
            raise ValueError('map_anchor_session_changed; explicit re-registration required')
        if str(context.reference.version.generation_id)!=self.source_generation or context.reference.version.revision<self.revision:
            raise ValueError('map_anchor_source_changed; explicit re-registration required')
        # Bound the maximum planar drift within the supported 20 m route disk.
        drift=math.hypot(binding.x-self.binding.x,binding.y-self.binding.y)+40*abs(math.sin(angle(binding.yaw-self.binding.yaw)/2))
        if drift>.1:raise ValueError('map_anchor_alignment_changed')
        if context.reference.version.revision==self.revision and context.sha256!=self.map_sha256:
            raise ValueError('map_anchor_content_changed')
