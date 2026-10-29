"""The actual Control Center HTTP contract, with independent Gazebo checks.

Only /api/manual/{action,start,state,update,stop} originate control requests.
No test calls a vehicle port, MAVLink sender or Gazebo publisher.
"""
from dataclasses import asdict
import json
import math
import time
from urllib.error import HTTPError

TERMINAL={'SUCCEEDED','FAILED','REJECTED','CANCELLED','TIMED_OUT','UNKNOWN'}


class ControlCheck:
    def __init__(self,kind,api,oracle,directory,*,target=None,expected_system_id=None):
        self.target=target or kind
        self.expected_system_id=expected_system_id or {"rover":1,"copter":2,"plane":3}[kind]
        self.kind=kind;self.api=api;self.oracle=oracle;self.directory=directory
        self.result=dict(kind=kind,passed=False,actions=[],information=[],managed=[],checks=[])
        self.last=None;self.initial=self.truth();self.started=time.monotonic()
        self.trace=(directory/'web-control-requests.jsonl').open('w')
        self.trajectory=(directory/'web-control-truth.jsonl').open('w')

    def save(self):
        (self.directory/'web-control-result.json').write_text(json.dumps(self.result,ensure_ascii=False,indent=2)+'\n')

    def call(self,path,payload=None):
        start=time.monotonic_ns()
        if payload is not None and payload.get("target")==self.kind:
            payload=dict(payload,target=self.target)
        try:value=self.api(path,payload)
        except HTTPError as exc:
            error=exc.read().decode(errors='replace')[:1000]
            self.trace.write(json.dumps(dict(at_ns=start,path=path,payload=payload,http_status=exc.code,error=error))+'\n');self.trace.flush()
            raise AssertionError(f'{path}: HTTP {exc.code}: {error}') from None
        if payload is not None:
            self.trace.write(json.dumps(dict(at_ns=start,path=path,payload=payload,elapsed_ms=(time.monotonic_ns()-start)/1e6,response=value))+'\n');self.trace.flush()
        return value

    def truth(self):
        sample=self.oracle.latest()
        if sample is None or time.monotonic_ns()-sample.host_received_ns>500_000_000:
            raise AssertionError('independent Gazebo truth unavailable/stale')
        if hasattr(self,'trajectory'):
            self.trajectory.write(json.dumps(dict(**asdict(sample),speed_mps=self.oracle.recent_speed_mps()))+'\n');self.trajectory.flush()
        return sample

    def wait(self,predicate,seconds=30):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            self.truth();value=predicate()
            if value:return value
            time.sleep(.1)
        raise TimeoutError('HTTP control/physical observation timeout')

    def information(self,label,*,armed=None,mode=None):
        v=self.call('/api/studio/state')['vehicles'][0];w=v['world'];state=w['vehicle']
        assert v['kind']==self.kind and v['connected'] and v['fresh_vehicle_state']
        assert v['verified_frames']>0 and not v['fault']
        assert state['health']['quality']=='VALID'
        pose=state['reported_pose'];twist=state['reported_twist'];op=state['operation']
        if 'display' in v:
            display=v['display'];assert display['mode_name'] and display['source_system']==self.expected_system_id
            assert display['pose_age_s'] is not None and 0<=display['pose_age_s']<=3
            assert math.isfinite(display['horizontal_speed_mps']) and display['control_hint']
        assert pose['frame_id']=='odom' and twist['frame_id'] in ('odom','base_link')
        p=pose['value']['position'];q=pose['value']['orientation'];velocity=twist['value']['linear']
        assert all(math.isfinite(x) for x in [*p.values(),*q.values(),*velocity.values()])
        truth=self.truth();error=math.dist([p['x'],p['y'],p['z']],[truth.x_m,truth.y_m,truth.z_m-self.initial.z_m])
        if armed is not None:assert op['armed']==armed,(label,op)
        if mode is not None:assert op['native_mode']==f'ARDUPILOT_CUSTOM_{mode}',(label,op)
        entry=dict(label=label,operation=op,position=p,velocity=velocity,orientation=q,
            health=state['health'],global_position=state['global_position'],
            truth_error_m=error,truth=asdict(truth),pose_captured_at=pose['captured_at'],
            observed_at_ns=time.monotonic_ns(),system_send=v['system_send'],action_send=v['action_send'])
        entry['display']=v.get('display')
        self.result['information'].append(entry);self.save()
        age=max(0,(entry['observed_at_ns']-pose['captured_at']['monotonic_ns'])/1e9)
        # Compare a live aircraft's delayed sample with current truth using its
        # explicit sample age and speed, rather than pretending simultaneous cuts.
        tolerance=2.+(self.oracle.recent_speed_mps() or 0)*age if self.kind=='plane' else 2.
        assert age<=3. and error<=tolerance,('Web position differs from time-qualified Gazebo',label,error,age,tolerance)
        return entry

    def state(self,identifier):return next(a for a in self.call('/api/instances') if a['id']==identifier)

    def finish(self,a,seconds=45,expected='SUCCEEDED'):
        def done():
            value=self.state(a['id'])
            return value if value['state'] in TERMINAL else None
        final=self.wait(done,seconds)
        self.result['actions'].append(final);self.save()
        assert final['state']==expected,(final['name'],final['state'],final['error'])
        safety=final['safety'];assert safety and (safety['release_safe'] or self.kind=='plane' and safety['continuation_allowed'])
        self.last=final['id'] if safety['continuation_allowed'] else None
        print(f'{self.kind}: {final["name"]} {final["state"]}',flush=True)
        return final

    def perform(self,name,parameters=None,seconds=45):
        request=dict(name=name,version='1.0.0',target=self.kind,parameters=parameters or {},allow_send=True)
        if self.last:request['continuation_of']=self.last
        return self.finish(self.call('/api/manual/action',request),seconds)

    def managed(self,name,parameters,threshold):
        start=self.truth()
        response=self.call('/api/manual/start',dict(name=name,target=self.kind,parameters=parameters,allow_send=True))
        session=response['session'];action=response['action']
        action=self.wait(lambda:(lambda a:a if a['state']=='RUNNING' else None)(self.call('/api/manual/state?session_id='+session['id'])),8)
        end=time.monotonic()+12;measured=0
        try:
            while time.monotonic()<end:
                time.sleep(.1)
                action=self.call('/api/manual/update',dict(session_id=session['id'],sequence=action['input_sequence']+1,deadline_ns=action['input_ticket'],parameters=parameters))
                assert action['state']=='RUNNING',action
                t=self.truth()
                measured=(math.hypot(t.x_m-start.x_m,t.y_m-start.y_m) if threshold[0]=='distance' else abs(math.atan2(math.sin(t.yaw_rad-start.yaw_rad),math.cos(t.yaw_rad-start.yaw_rad))))
                if measured>=threshold[1]:break
            else:raise AssertionError('managed motion did not physically occur')
        finally:self.call('/api/manual/stop',dict(session_id=session['id']))
        final=self.finish(action,20,expected='CANCELLED')
        speed=self.oracle.recent_speed_mps();yaw_rate=self.oracle.recent_yaw_rate_rad_s()
        assert speed is not None and speed<=(.1 if self.kind=='rover' else .15)
        assert yaw_rate is not None and abs(yaw_rate)<=(.1 if self.kind=='rover' else .15)
        self.result['managed'].append(dict(parameters=parameters,measured=measured,stop_speed_mps=speed,stop_yaw_rate_rad_s=yaw_rate,state=final['state']))
        self.save()

    def run(self):
        try:
            self.information('initialized',armed=False)
            modes={'rover':[('GUIDED',15),('HOLD',4),('GUIDED',15)],'copter':[('GUIDED',4),('LOITER',5),('GUIDED',4)],'plane':[('MANUAL',0)]}[self.kind]
            for name,number in modes:
                self.perform('SetMode',{'mode':name});self.information('mode '+name,mode=number)
            self.perform('Arm');self.information('armed',armed=True)
            self.perform('Disarm');self.information('disarmed',armed=False)
            self.perform('Arm');self.information('rearmed',armed=True)
            if self.kind=='rover':
                self.perform('Stop')
                self.information('Stop from GUIDED',armed=True,mode=4)
            if self.kind=='plane':self.plane()
            else:self.hover_or_ground()
            self.result.update(passed=True,elapsed_s=time.monotonic()-self.started)
        except Exception as exc:
            self.result['error']=type(exc).__name__+': '+str(exc)
            raise
        finally:
            self.save();self.trace.close();self.trajectory.close()
        return self.result

    def hover_or_ground(self):
        if self.kind=='copter':
            self.perform('Takeoff',{'height_m':1.5},45)
            self.information('airborne',armed=True)
            assert abs(self.truth().z_m-self.initial.z_m-1.5)<=.35
        for turn in (False,True):
            self.perform('SetMode',{'mode':'GUIDED'})
            if self.kind=='rover':p=dict(speed_mps=0 if turn else .3,yaw_rate_rad_s=.25 if turn else 0);name='Drive'
            else:p=dict(vx_mps=0 if turn else .3,vy_mps=0,vz_mps=0,yaw_rate_rad_s=.25 if turn else 0,frame='base_link');name='SetVelocity'
            self.managed(name,p,('yaw',.4) if turn else ('distance',.5))
            self.information('turn stopped' if turn else 'forward stopped',armed=True)
        if self.kind=='rover':
            self.perform('Stop')
            self.information('Stop while already HOLD',armed=True,mode=4)
        self.perform('SetMode',{'mode':'GUIDED'})
        self.perform('Goto',dict(x_m=2.,y_m=0.,z_m=0. if self.kind=='rover' else 1.5),55)
        self.information('goto',armed=True,mode=4 if self.kind=='rover' else None)
        self.perform('ReturnHome',seconds=65)
        if self.kind=='rover':self.perform('Disarm')
        self.information('home stopped',armed=False)
        t=self.truth();error=math.hypot(t.x_m-self.initial.x_m,t.y_m-self.initial.y_m)
        assert error<=.75 and self.oracle.recent_speed_mps()<=(.1 if self.kind=='rover' else .15)
        self.result['home_error_m']=error

    def plane(self):
        self.perform('Takeoff',{'height_m':50},125)
        self.information('climbed',armed=True)
        takeoff=self.truth();assert 45<=takeoff.z_m-self.initial.z_m<=55
        assert math.hypot(takeoff.x_m-self.initial.x_m,takeoff.y_m-self.initial.y_m)>10
        geo=self.result['information'][0]['global_position']['value']
        latitude=geo['latitude_deg']+150/6378137*180/math.pi
        longitude=geo['longitude_deg']+300/(6378137*math.cos(math.radians(geo['latitude_deg'])))*180/math.pi
        begin=self.truth()
        self.perform('SetGuidedTarget',dict(latitude_deg=latitude,longitude_deg=longitude,altitude_amsl_m=geo['altitude_m']+50),35)
        self.wait(lambda:abs(math.atan2(math.sin(self.truth().yaw_rad-begin.yaw_rad),math.cos(self.truth().yaw_rad-begin.yaw_rad)))>=.5,50)
        self.information('guided turn',armed=True)
        self.perform('Loiter',seconds=35)
        self.information('stop means native loiter',armed=True,mode=12)
        assert self.oracle.recent_speed_mps()>7,'Plane must retain flying speed, never zero-speed hover'
        self.perform('RTL',seconds=35)
        self.information('RTL mode',armed=True,mode=11)
        self.wait(lambda:math.hypot(self.truth().x_m-self.initial.x_m,self.truth().y_m-self.initial.y_m)<=120,110)
        self.result['checks'].append('native RTL physically approached home; mode adoption alone is not arrival')
        self.perform('AutoLand',seconds=410)
        self.information('landed and disarmed',armed=False)
        landed=self.truth()
        distance=math.hypot(landed.x_m-self.initial.x_m,landed.y_m-self.initial.y_m)
        assert abs(landed.z_m-self.initial.z_m)<.25 and self.oracle.recent_speed_mps()<1
        assert distance<=80 and abs(landed.y_m-self.initial.y_m)<=15


def exercise(kind,api,oracle,directory):return ControlCheck(kind,api,oracle,directory).run()
