"""Phase 4 real graph logic, ownership, link-loss/restart and safe reconstruction."""
import argparse
import json
from pathlib import Path
from threading import Event,Thread
import time
from urllib.error import HTTPError

from tests.simulation.launch import install_signal_cleanup
from tests.simulation.mission_fixture import MissionFixture
from tests.simulation.mission_physics import no_expired_motion


def until(f,predicate,seconds=20):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        f.truth();v=predicate()
        if v:return v
        time.sleep(.05)
    raise TimeoutError('real Phase 4 boundary')


def denied(f,route,payload):
    try:f.api(route,payload)
    except HTTPError as e:
        if e.code!=409:raise
        return json.load(e)
    raise AssertionError('unsafe/conflicting request accepted')


def spec(kind,identifier,nodes,root='root',**kw):
    return dict(schema_version=1,id=identifier,name=identifier,version='1.0.0',target=kind,root=root,nodes=nodes,timeout_s=60,**kw)


def query(identifier):return dict(id=identifier,type='Action',action='GetVehicleState',parameters={})


def logic(f):
    nodes=[dict(id='root',type='Sequence',children=['parallel','fallback','event','repeat','timeout-recovery','reactive','race','main']),
        dict(id='parallel',type='Parallel',completion='all',failure='fail_fast',children=['q1','wait1']),query('q1'),dict(id='wait1',type='Wait',duration_s=.15),
        dict(id='fallback',type='Fallback',children=['false','q2']),dict(id='false',type='Condition',expression=dict(op='eq',source='blackboard',path='ready',value=True)),query('q2'),
        dict(id='event',type='Event',event='sim.ready',children=['q3']),query('q3'),
        dict(id='repeat',type='Repeat',count=2,children=['q4']),query('q4'),
        dict(id='timeout-recovery',type='Recovery',children=['timeout','q5']),dict(id='timeout',type='Timeout',timeout_s=.15,children=['slow']),dict(id='slow',type='Wait',duration_s=2),query('q5'),
        dict(id='reactive',type='Reactive',event='sim.react',children=['main-wait','q6']),dict(id='main-wait',type='Wait',duration_s=5),query('q6'),
        dict(id='race',type='Parallel',completion='any',failure='all_failed',children=['winner','loser']),dict(id='winner',type='Wait',duration_s=.1),dict(id='loser',type='Wait',duration_s=2),
        dict(id='main',type='Parallel',completion='main',failure='fail_fast',children=['q7','background']),query('q7'),dict(id='background',type='Wait',duration_s=5)]
    d=spec(f.kind,'logic-matrix',nodes,blackboard={'ready':False})
    r=f.api('/api/missions/start',dict(spec=d,allow_send=False));sent=set()
    def finished():
        v=f.lab.missions.view(r['id'])
        for node,name in [('event','sim.ready'),('reactive','sim.react')]:
            if node not in sent and any(n['id']==node and n['state']=='RUNNING' for n in v['nodes']):
                # Expired input must not trigger the node; a new valid identity does.
                from dataclasses import replace
                old=replace(f.lab.clock(),monotonic_ns=f.lab.clock().monotonic_ns-10_000_000_000)
                f.lab.events.publish('expired-'+node,name,{'test':True},old,ttl_s=1)
                if f.lab.events.read(f.lab.events.cursor-1,name,f.lab.clock()):raise AssertionError('expired event accepted')
                if not f.lab.events.publish('fresh-'+node,name,{'test':True},f.lab.clock()):raise AssertionError('new event rejected')
                if f.lab.events.publish('fresh-'+node,name,{'test':True},f.lab.clock()):raise AssertionError('duplicate event accepted')
                sent.add(node)
        if v['state'] in ('UNKNOWN','FAILED','REJECTED','TIMED_OUT'):raise AssertionError('logic graph '+str(v))
        return v if v['state']=='SUCCEEDED' else None
    value=until(f,finished,20)
    if f.writer or not value['release_safe']:raise AssertionError('query/logic graph wrote or retained danger')
    return dict(passed=True,mission=value,actual_writer_calls=0,expired_and_duplicate_events_rejected=True)


class Managed:
    def __init__(self,f):
        self.f=f;self.stop_event=Event();self.error=None
        self.parameters={'speed_mps':.3} if f.kind=='rover' else {'vx_mps':.2,'frame':'odom'}
        self.request=dict(name='Drive' if f.kind=='rover' else 'SetVelocity',target=f.kind,parameters=self.parameters,allow_send=True)
        r=f.api('/api/manual/start',self.request);self.session=r['session'];self.action=r['action']
        def update():
            while not self.stop_event.wait(.1):
                a=f.lab.runtime.view(self.action['id'])
                if a['state'] in ('CANCELLED','TIMED_OUT','UNKNOWN','FAILED','REJECTED'):return
                if a['state']!='RUNNING':continue
                try:f.api('/api/manual/update',dict(session_id=self.session['id'],sequence=a['input_sequence']+1,deadline_ns=a['input_deadline_ns'],parameters=self.parameters))
                except Exception as exc:self.error=type(exc).__name__+': '+str(exc);return
        self.thread=Thread(target=update,daemon=True);self.thread.start()
        until(f,lambda:f.lab.runtime.view(self.action['id'])['state']=='RUNNING',4)
    def stop_updates(self):self.stop_event.set();self.thread.join(2)
    def cancel(self):
        self.stop_updates();self.f.api('/api/manual/stop',{'session_id':self.session['id']})
        return self.f.wait_action(self.action,state='CANCELLED',timeout=16)


def run(path,kind):
    path.mkdir(parents=True,exist_ok=False);f=MissionFixture(path/'original',kind);recovery=None;managed=None
    result=dict(passed=False,kind=kind)
    try:
        f.start();result['logic']=logic(f)
        for name,params in [('SetMode',{'mode':'GUIDED'}),('Arm',{})]:f.wait_action(f.action(name,params))
        if kind=='copter':f.wait_action(f.action('Takeoff',{'height_m':1.5}))
        managed=Managed(f);f.pause(1)
        pose=f.driver.snapshot().vehicle.reported_pose.value.position
        d=spec(kind,'handoff', [dict(id='root',type='Sequence',children=['mode','wait','goto']),
            dict(id='mode',type='Action',action='SetMode',parameters={'mode':'GUIDED'}),dict(id='wait',type='Wait',duration_s=.3),
            dict(id='goto',type='Action',action='Goto',parameters=dict(x_m=pose.x+1,y_m=pose.y,z_m=0 if kind=='rover' else 1.5))])
        count=len(f.lab.runtime.views());denied(f,'/api/missions/start',dict(spec=d,allow_send=True))
        if len(f.lab.runtime.views())!=count:raise AssertionError('manual conflict created a Mission Action')
        managed.stop_updates();f.api('/api/control/takeover',{'target':kind});f.wait_action(managed.action,state='CANCELLED',timeout=16)
        r=f.api('/api/missions/start',dict(spec=d,allow_send=True))
        denied(f,'/api/manual/start',managed.request)
        until(f,lambda:any(a['name']=='Goto' and a['state']=='RUNNING' and a['effects'] for a in f.lab.runtime.views()),15)
        f.api('/api/control/takeover',{'target':kind});denied(f,'/api/manual/start',managed.request)
        mission=f.wait_mission(r['id'],state='CANCELLED',timeout=18)
        if not mission['release_safe']:raise AssertionError('cancelled Mission did not safely release')
        old=managed
        if kind=='rover':f.wait_action(f.action('SetMode',{'mode':'GUIDED'}))
        managed=Managed(f);f.pause(1)
        old_value=old.action;denied(f,'/api/manual/update',dict(session_id=old.session['id'],sequence=1,deadline_ns=old_value['input_deadline_ns'],parameters=old.parameters))
        result['handoff']=dict(passed=True,manual_to_mission=True,mission_to_manual=True,conflicting_new_motion_writer_calls=0,
            cancelling_takeover_rejected=True,old_input_rejected=True,cancelled_mission=mission)
        managed.cancel()
        if kind=='rover':f.wait_action(f.action('SetMode',{'mode':'GUIDED'}))
        managed=Managed(f);f.pause(1)
        f.proxy.inject(drop_rx=True);managed.stop_updates()
        uncertain=f.wait_action(managed.action,state='UNKNOWN',timeout=18)
        if uncertain['safety']['release_safe'] or not f.lab.runtime.resource_view():raise AssertionError('link loss released unknown motion')
        before=len(f.writer)
        denied(f,'/api/manual/start',managed.request)
        raw=f.lab.runtime.submit(managed.request['name'],kind,managed.parameters,allow_send=True,input_timeout_s=.4)
        if raw['state']!='REJECTED':raise AssertionError('raw Runtime bypassed uncertain motion claim')
        f.pause(.3)
        if len(f.writer)!=before:raise AssertionError('UNKNOWN rejection wrote new commands')
        result['link_loss']=dict(passed=True,final=uncertain,rejected_new_writer_calls=0,deadline=no_expired_motion(f,uncertain))
        f.proxy.inject(drop_rx=False);old_session=managed.session['id'];old_vehicle_session=f.driver.info()['session_id']
        f.reopen_application()
        if f.driver.info()['system_send'] or f.driver.info()['action_send'] or f.driver.info()['lease_active']:raise AssertionError('restart inherited authorization')
        if f.driver.info()['session_id']==old_vehicle_session:raise AssertionError('reconnect reused link session')
        before=len(f.writer)
        denied(f,'/api/manual/update',dict(session_id=old_session,sequence=1,deadline_ns=uncertain['input_deadline_ns'],parameters=managed.parameters))
        denied(f,'/api/manual/start',managed.request)
        denied(f,'/api/control/reestablish',{'target':kind})
        f.pause(.3)
        if len(f.writer)!=before:raise AssertionError('read-only restart wrote vehicle commands')
        result['restart']=dict(passed=True,writer_calls=0,state=f.api('/api/studio/state'),old_session_rejected=True,armed_reconstruction_rejected=True)
        f.close()
        recovery=MissionFixture(path/'recovery',kind,application_dir=f.application_dir,provider_registry_root=f.provider_registry_root).start()
        before=len(recovery.writer)
        denied(recovery,'/api/manual/start',managed.request)
        proof=recovery.api('/api/control/reestablish',{'target':kind})
        if recovery.writer or not proof['new_send_required']:raise AssertionError('reconstruction sent commands or granted SEND')
        readonly=recovery.api('/api/manual/action',dict(name='SetMode',target=kind,parameters={'mode':'GUIDED'}))
        recovery.wait_action(readonly,state='REJECTED')
        if recovery.writer:raise AssertionError('post-reconstruction default SEND wrote')
        for name,params in [('SetMode',{'mode':'GUIDED'}),('Arm',{}),('Disarm',{})]:recovery.wait_action(recovery.action(name,params))
        state=recovery.api('/api/studio/state')
        if not any(a['state']=='UNKNOWN' and a['release_safe'] for a in state['recovered_actions']):raise AssertionError('old UNKNOWN history overwritten/lost')
        result['controlled_recovery']=dict(passed=True,evidence=proof,default_send_writer_calls=0,positive_writer_calls=len(recovery.writer),state=state)
        result['passed']=True
    except BaseException as exc:
        result['error']=type(exc).__name__+': '+str(exc)
        if f.driver:result['driver_info']=f.driver.info()
        if f.proxy:result['proxy_error']=f.proxy.error
        raise
    finally:
        if managed:managed.stop_updates()
        try:
            if recovery:recovery.close()
            # close once: an ended manifest is evidence, not a reset button.
            if not f.owned.manifest.get('ended_at'):f.close()
        finally:(path/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kind',choices=('rover','copter'),required=True);p.add_argument('--run-dir',type=Path,required=True)
    a=p.parse_args();install_signal_cleanup();v=run(a.run_dir.resolve(),a.kind);print(a.kind,'Mission fault/restart',v['passed'],flush=True)
if __name__=='__main__':main()
