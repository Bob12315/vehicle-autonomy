"""Real Plane Mission/manual native continuation and ambiguous cancellation."""
import argparse
import json
import math
from pathlib import Path
from tests.simulation.launch import install_signal_cleanup
from tests.simulation.mission_fixture import MissionFixture
from tests.simulation.phase4_faults import denied,until,spec


def continuation(path):
    f=MissionFixture(path,'plane');result=dict(passed=False)
    try:
        f.start()
        d=spec('plane','flight-mission',[dict(id='root',type='Sequence',children=['mode','arm','takeoff']),
            dict(id='mode',type='Action',action='SetMode',parameters={'mode':'MANUAL'}),
            dict(id='arm',type='Action',action='Arm',parameters={}),dict(id='takeoff',type='Action',action='Takeoff',parameters={'height_m':50})])
        d['timeout_s']=180
        r=f.api('/api/missions/start',dict(spec=d,allow_send=True));first=f.wait_mission(r['id'],timeout=190)
        t=f.truth()
        if not first['continuation_allowed'] or first['release_safe'] or t.z_m-f.initial.z_m<45:
            raise AssertionError('completed airborne Mission did not retain native flight')
        before=len(f.writer);denied(f,'/api/manual/action',dict(name='Loiter',target='plane',parameters={},allow_send=True))
        if len(f.writer)!=before:raise AssertionError('unauthorized native takeover wrote')
        manual=f.wait_action(f.action('Loiter',continuation_of=first['continuation_of']),timeout=40)
        old=f.lab.missions.view(r['id'])
        if not manual['safety']['continuation_allowed'] or not old['release_safe'] or old['continuation_allowed']:
            raise AssertionError('Mission -> manual native resource transfer inconsistent')
        landing=spec('plane','landing-mission',[dict(id='root',type='Sequence',children=['query','rtl','land']),
            dict(id='query',type='Action',action='GetVehicleState',parameters={}),dict(id='rtl',type='Action',action='RTL',parameters={}),
            dict(id='land',type='Action',action='AutoLand',parameters={})]);landing['timeout_s']=600
        second=f.api('/api/missions/start',dict(spec=landing,allow_send=True,continuation_of=manual['id']))
        final=f.wait_mission(second['id'],timeout=620);t=f.truth();distance=math.hypot(t.x_m-f.initial.x_m,t.y_m-f.initial.y_m)
        if not final['release_safe'] or final['continuation_allowed'] or t.z_m-f.initial.z_m>.25 or f.oracle.recent_speed_mps()>=1 or distance>80 or abs(t.y_m-f.initial.y_m)>15:
            raise AssertionError('manual -> Mission AUTOLAND not physically safe/within original runway limits')
        from pymavlink.dialects.v20 import ardupilotmega as mav
        frame_types=[m.get_type() for w in f.writer for m in mav.MAVLink(None).parse_buffer(bytes.fromhex(w['raw_hex'])) or []]
        if any(t in ('SET_POSITION_TARGET_LOCAL_NED','RC_CHANNELS_OVERRIDE','MANUAL_CONTROL') for t in frame_types):
            raise AssertionError('Plane handoff used hover/RC/game controls')
        result.update(passed=True,first_mission=first,transferred_mission=old,manual=manual,landing_mission=final,
            physical=dict(landing_error_m=distance,height_m=t.z_m-f.initial.z_m,speed_mps=f.oracle.recent_speed_mps()),writer=f.writer,
            unauthorized_writer_calls=0,zero_velocity_or_rc_writer_calls=0)
    except BaseException as exc:result['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        try:f.close()
        finally:(path/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def ambiguous_cancel(path):
    f=MissionFixture(path,'plane');result=dict(passed=False)
    try:
        f.start();f.wait_action(f.action('SetMode',{'mode':'MANUAL'}))
        old_ack=next(r for r in reversed(f.received) if r['type']=='COMMAND_ACK' and r['payload']['command']==176)
        old_hb=next(r for r in reversed(f.received) if r['type']=='HEARTBEAT' and not r['payload']['base_mode']&128)
        f.wait_action(f.action('Arm'))
        from pymavlink.dialects.v20 import ardupilotmega as mav
        sequences=[]
        for v in f.received:
            for m in mav.MAVLink(None).parse_buffer(bytes.fromhex(v['raw_hex'])) or []:
                if m.get_srcSystem()==1 and m.get_srcComponent()==1:sequences.append(m.get_seq())
        wraps=sum(a-b>128 for a,b in zip(sequences,sequences[1:]))
        if wraps<2:raise AssertionError('real proxy did not observe multiple complete packet sequence wraps')
        cutoff=f.lab.clock().monotonic_ns;f.proxy.inject(drop_ack_command=176)
        d=spec('plane','uncertain-takeoff',[dict(id='root',type='Fallback',children=['takeoff','recovery']),
            dict(id='takeoff',type='Action',action='Takeoff',parameters={'height_m':50}),dict(id='recovery',type='Action',action='Loiter',parameters={})]);d['timeout_s']=180
        r=f.api('/api/missions/start',dict(spec=d,allow_send=True))
        until(f,lambda:any(m.get('host_ns',0)>=cutoff and m.get('direction')=='rx_discard' and m.get('cause')=='filter'
            and m.get('type')=='COMMAND_ACK' and m.get('payload',{}).get('command')==176 for m in f.proxy.records),5)
        replay_cutoff=f.lab.clock().monotonic_ns
        intercepted=[m for m in f.proxy.records if cutoff<=m.get('host_ns',0)<=replay_cutoff and m.get('direction')=='rx_discard'
            and m.get('cause')=='filter' and m.get('type')=='COMMAND_ACK' and m.get('payload',{}).get('command')==176]
        forwarded=[m for m in f.proxy.records if cutoff<=m.get('host_ns',0)<=replay_cutoff and m.get('direction')=='rx_forward'
            and m.get('type')=='COMMAND_ACK' and m.get('payload',{}).get('command')==176]
        received=[m for m in f.received if cutoff<=m['host_ns']<=replay_cutoff and m['type']=='COMMAND_ACK' and m['payload']['command']==176]
        if not intercepted or forwarded or received:raise AssertionError('new TAKEOFF ACK drop not actually effective')
        if f.driver.snapshot().vehicle.operation.armed is not True:raise AssertionError('replay comparison requires actual new armed state')
        rejected=f.driver.ownership.receive_signing.rejected['replay']
        f.proxy.replay_rx(bytes.fromhex(old_ack['raw_hex']));f.proxy.replay_rx(bytes.fromhex(old_hb['raw_hex']))
        until(f,lambda:f.driver.ownership.receive_signing.rejected['replay']>=rejected+2,3)
        f.pause(.3)
        current=f.lab.missions.view(r['id']);action=f.lab.runtime.view(current['action_ids'][0])
        if action['state']=='SUCCEEDED' or any(v['phase']=='COMPLETED' for v in action['command_results']):
            raise AssertionError('old ACK/HEARTBEAT replay completed new TAKEOFF')
        if f.driver.snapshot().vehicle.operation.armed is not True:raise AssertionError('old heartbeat regressed actual trusted armed state')
        f.api('/api/missions/cancel',{'id':r['id']});uncertain=f.wait_mission(r['id'],state='UNKNOWN',timeout=18)
        if uncertain['release_safe'] or uncertain['continuation_allowed'] or len(uncertain['action_ids'])!=1:
            raise AssertionError('UNKNOWN Plane Mission advanced fallback or released native flight')
        before=len(f.writer)
        denied(f,'/api/manual/action',dict(name='Loiter',target='plane',parameters={},allow_send=True,continuation_of=action['id']))
        raw=f.lab.runtime.submit('Loiter','plane',allow_send=True,continuation_of=action['id'])
        if raw['state']!='REJECTED':raise AssertionError('UNKNOWN native handoff bypassed common resources')
        try:f.lab.runtime.resources.release(uncertain['resource_group_id'],no_effects=True)
        except ValueError:pass
        else:raise AssertionError('ordinary release cleared uncertain Mission group')
        f.pause(.3)
        if len(f.writer)!=before:raise AssertionError('rejected unknown handoff wrote')
        result.update(passed=True,packet_wraps=wraps,old_signed_replays_rejected=2,old_state_regression=False,
            new_ack=dict(dropped=len(intercepted),forwarded=len(forwarded),application_received=len(received)),
            uncertain=uncertain,command=action,unsafe_handoff_writer_calls=0,writer=f.writer)
    except BaseException as exc:result['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        try:f.close()
        finally:(path/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args();install_signal_cleanup()
    root=a.run_dir.resolve();root.mkdir(parents=True,exist_ok=False)
    r=dict(passed=False)
    try:r.update(continuation=continuation(root/'continuation'),uncertain=ambiguous_cancel(root/'uncertain'));r['passed']=True
    finally:(root/'summary.json').write_text(json.dumps(r,indent=2)+'\n')
    print('Plane Mission handoff/UNKNOWN',r['passed'],flush=True)
if __name__=='__main__':main()
