"""Bounded, expiring proposals. Admission creates no Action and no SEND."""
from copy import deepcopy
from threading import RLock
import math
import time

from vehicle_autonomy.app.tools.schema import identifier,object_fields
from .state import finite_vector,snapshot


class PendingGoals:
    def __init__(self,service,*,clock=time.monotonic):self.service=service;self.clock=clock;self.lock=RLock();self.records={}

    def submit(self,payload):
        object_fields(payload,('id','target','epoch','frame','position','orientation'),('ros_frame',))
        identifier(payload['id']);identifier(payload['target'])
        if payload['frame'] not in ('odom','map'):raise ValueError('only explicit odom or preview-only map goals are accepted')
        if 'ros_frame' in payload:
            import re
            if type(payload['ros_frame']) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_/]{0,149}',payload['ros_frame']):raise ValueError('bounded ROS source frame required')
        p=finite_vector(payload['position'],3);q=finite_vector(payload['orientation'],4)
        if abs(sum(v*v for v in q)-1)>1e-6 or max(abs(v) for v in p)>5000:raise ValueError('invalid goal pose or projection extent')
        source=snapshot(self.service,payload['target'])
        if not source['valid'] or payload['epoch']!=source['epoch']:raise ValueError('goal source epoch or localization is stale/invalid')
        with self.lock:
            now=self.clock();self.records={k:v for k,v in self.records.items() if v['expires']>now}
            key=payload['id'];old=self.records.get(key)
            if old:
                if old['request']!=payload:raise ValueError('proposal identity reused for different goal')
                return self._view(old)
            if len(self.records)>=64:raise ValueError('pending goal budget exhausted')
            recent=[v for v in self.records.values() if v['request']['target']==payload['target'] and now-v['created']<.2]
            if recent:raise ValueError('goal proposal rate exceeds 5 Hz')
            executable=payload['frame']=='odom' and source['kind']=='rover' and abs(p[2])<.01
            record=dict(request=deepcopy(payload),created=now,expires=now+30,action_id=None,
                observed_at=self.service.clock(),
                executable=executable,reason=None if executable else 'Preview only: no qualified map transform/Nav2 execution or aircraft goal interface; Rover execution requires odom ground coordinates')
            self.records[key]=record;return self._view(record)

    def _view(self,r):return dict(**deepcopy(r['request']),remaining_s=max(0,r['expires']-self.clock()),action_id=r['action_id'],executable=r['executable'],reason=r['reason'],execution_semantics='Existing Goto executes position only; selected orientation is preview-only')

    def view(self,target):
        with self.lock:return [self._view(v) for v in self.records.values() if v['request']['target']==target and v['expires']>self.clock()][-10:]

    def read_input(self,target,binding,now):
        """Read a proposal as data; this method cannot create an Action."""
        from vehicle_autonomy.contracts.mission import BlackboardValue
        with self.lock:
            record=self.records.get(binding['id'])
            if record is None or record['request']['target']!=target or record['expires']<=self.clock():raise ValueError('navigation input missing, expired or wrong vehicle')
            source=snapshot(self.service,target)
            if not source['valid'] or source['epoch']!=record['request']['epoch'] or record['request']['frame']!='odom':raise ValueError('navigation input epoch/frame unavailable; map transform is not qualified')
            index={'position.x':0,'position.y':1,'position.z':2}.get(binding['path'])
            if index is None:raise ValueError('only position data import is supported; orientation is not executed')
            return BlackboardValue(record['request']['position'][index],record['observed_at'],30_000_000_000,frame='odom',source='navigation_goal:'+binding['id'])

    def execute(self,payload,submit):
        object_fields(payload,('id','target','allow_send'))
        if payload['allow_send'] is not True:raise ValueError('explicit one-action SEND confirmation required')
        with self.lock:
            r=self.records[payload['id']];source=snapshot(self.service,payload['target'])
            if r['request']['target']!=payload['target'] or r['expires']<=self.clock() or not r['executable']:raise ValueError('goal expired, wrong vehicle or preview-only')
            if r['action_id']:raise ValueError('goal already submitted; no duplicate execution')
            if not source['valid'] or source['epoch']!=r['request']['epoch']:raise ValueError('localization changed since goal selection')
            p=r['request']['position'];result=submit(dict(name='Goto',target=payload['target'],parameters=dict(x_m=p[0],y_m=p[1],z_m=0.),allow_send=True))
            r['action_id']=result['id'];return result
