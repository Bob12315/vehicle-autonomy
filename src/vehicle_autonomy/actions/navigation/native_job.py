"""Registered native Nav2 macro. All native producers must stop before release.

The source reader and Goal client have no MAVLink or vehicle command port.
A private worker status file carries original producer evidence, never authority.
"""
from contextvars import copy_context
from copy import deepcopy
import json
import math
import re
import os
from pathlib import Path
import stat
from threading import Event,RLock,Thread
import time
from uuid import uuid4
from vehicle_autonomy.engine.action.external_lifecycle import register_job,require_job_scope
from vehicle_autonomy.world.mapping.grid import atomic_json


class NativeNavigationJob:
    def __init__(self,identity,goal,*,security_environment,world_name,clock_domain,cohort_factory):
        require_job_scope();self._identity=identity;verified=identity.identity()
        fields={'goal_id','action_id','target_id','vehicle_session','world_generation','map_epoch','x_m','y_m','yaw_rad','provider_id','provider_epoch'}
        if type(goal) is not dict or set(goal)!=fields or not isinstance(goal['goal_id'],str) or not re.fullmatch('[0-9a-f]{32}',goal['goal_id']):raise ValueError('sealed bounded native Goal required')
        if any(not isinstance(goal[k],str) or not 1<=len(goal[k])<=256 for k in fields-{'x_m','y_m','yaw_rad'}):raise ValueError('bounded native Goal identities required')
        if any(type(goal[k]) not in (int,float) or not math.isfinite(goal[k]) or abs(goal[k])>(math.pi if k=='yaw_rad' else 5) for k in ('x_m','y_m','yaw_rad')):raise ValueError('native coordinate bounds')
        if (goal['provider_id'],goal['provider_epoch'],world_name,clock_domain)!=(verified['provider_id'],verified['provider_epoch'],identity.provider_epoch,'host-monotonic-simulation'):raise ValueError('native physical provider/time identity mismatch')
        self._lock=RLock();self._cancel=Event();self._status={'state':'RUNNING','feedback':{'phase':'BOOTING'}}
        self._cohort=None;self._root=None;self._error=None;self.goal_id=goal['goal_id']
        if not callable(cohort_factory):raise TypeError('trusted native process factory required')
        self._cohort_factory=cohort_factory
        self._goal=dict(goal);self._security=dict(security_environment);self._world=world_name;self._clock=clock_domain
        register_job(self,'native',verified['locator'],provider_id=verified['provider_id'],provider_epoch=verified['provider_epoch'])
        context=copy_context();self._thread=Thread(target=context.run,args=(self._run,),name='native-navigation-'+self.goal_id,daemon=True);self._thread.start()
    @staticmethod
    def _read(path):
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink not in (0,1) or info.st_size>65536:raise ValueError('native status ownership/budget')
            raw=os.read(fd,65537)
            if len(raw)>65536:raise ValueError('native status budget')
            value=json.loads(raw)
            if type(value) is not dict:raise ValueError('native status object required')
            return value
        finally:os.close(fd)
    def _publish(self,value):
        with self._lock:self._status=value
    def _run(self):
        candidate=None;safe=False;cancel_at=None
        try:
            self._identity.identity();root=self._identity.root/'native-navigation-jobs'/self.goal_id
            root.mkdir(mode=0o700);self._root=root
            cohort=self._cohort=self._cohort_factory(root/'cohort','/nav2_wire',self._security)
            cohort.start(cancelled=self._cancel.is_set)
            if self._cancel.is_set():raise RuntimeError('native startup cancelled')
            address='@vaf-native-'+str(os.getuid())+'-'+self.goal_id
            receiver=cohort.source_receiver(address)
            receiver_ticks=Path(f'/proc/{receiver.pid}/stat').read_text().rsplit(')',1)[1].split()[19]
            config=dict(schema=1,directory=str(root),namespace='/nav2_wire',world=self._world,clock_domain=self._clock,goal=self._goal,source_receiver=dict(address=address,pid=receiver.pid,start_ticks=receiver_ticks))
            path=root/'goal.json';atomic_json(path,config);worker=cohort.goal_worker(path)
            while worker.poll() is None:
                # A trusted logical result can precede DDS process shutdown.
                # Surface it promptly so the vehicle can begin parking; this
                # still grants NO external safe-exit proof until stop() below.
                if (root/'terminal.json').exists():
                    candidate=self._read(root/'terminal.json')
                    if candidate.get('goal_id')!=self.goal_id or candidate.get('state') not in ('SUCCEEDED','FAILED','CANCELLED','UNKNOWN'):raise ValueError('native result identity/state mismatch')
                    break
                cohort.assert_alive();self._identity.identity()
                if self._cancel.is_set():
                    if cancel_at is None:atomic_json(root/'cancel.json',{'goal_id':self.goal_id});cancel_at=time.monotonic()
                    elif time.monotonic()-cancel_at>2:break
                try:
                    value=self._read(root/'state.json')
                    if value.get('goal_id')!=self.goal_id or value.get('state')!='RUNNING':raise ValueError('native worker identity/state mismatch')
                    self._publish(value)
                except FileNotFoundError:pass
                time.sleep(.02)
            if (root/'terminal.json').exists():
                candidate=self._read(root/'terminal.json')
                if candidate.get('goal_id')!=self.goal_id or candidate.get('state') not in ('SUCCEEDED','FAILED','CANCELLED','UNKNOWN'):raise ValueError('native result identity/state mismatch')
        except Exception as exc:self._error=type(exc).__name__+': '+str(exc)[:160]
        finally:
            self._publish(dict(state='RUNNING',feedback=dict(phase='EXITING',native_result=candidate)))
            safe=self._cohort is None # Constructor performs no process/Goal side effect.
            if self._cohort:
                try:safe=self._cohort.stop()
                except Exception:safe=False
            # Terminal is safe-exit evidence only AFTER the entire controlled
            # source cohort is gone, even when cancel/Goal result was lost.
            if safe:
                state='CANCELLED' if self._cancel.is_set() else 'SUCCEEDED' if candidate and candidate['state']=='SUCCEEDED' else 'FAILED'
                self._publish(dict(state=state,result=dict(native_result=candidate,producers_stopped=True),error=None if state=='SUCCEEDED' else 'native operation ended; controlled producer shutdown verified',detail=self._error))
            else:self._publish(dict(state='UNKNOWN',error='native producer shutdown unconfirmed',detail=self._error))
    def poll(self):
        with self._lock:return deepcopy(self._status)
    def cancel(self):self._cancel.set()
    def close(self):self.cancel();self._thread.join(.1)
    def reconcile(self):
        # Read-only recovery of this already-cancelled local cohort. Never
        # respawn, resubmit a Goal or treat leader PID death as remote exit.
        value=self.poll()
        if value['state']=='UNKNOWN' and not self._thread.is_alive() and self._cohort and self._cohort.stopped_proof():
            self._publish(dict(state='FAILED',result=dict(producers_stopped=True,native_result=None),error='operation result unknown; complete controlled producer exit verified'))
        return self.poll()
    def recovery_descriptor(self):
        return dict(protocol='native',goal_id=self.goal_id,provider=self._identity.identity(),directory=None if self._root is None else str(self._root),verification='controlled_native_cohort_shutdown_required')
