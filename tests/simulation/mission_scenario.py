"""Real Mission Graph -> Action Runtime -> existing signed AP/Gazebo chain."""
import argparse
import json
import math
from pathlib import Path
import time

from tests.simulation.launch import install_signal_cleanup
from tests.simulation.mission_fixture import MissionFixture


def build_mission(kind):
    nodes=[];children=[]
    def action(name,params=None,**kw):
        identifier='step'+str(len(children)+1);children.append(identifier)
        nodes.append(dict(id=identifier,type='Action',action=name,parameters=params or {},children=[],**kw))
    def wait(duration):
        identifier='wait'+str(len(children));children.append(identifier);nodes.append(dict(id=identifier,type='Wait',duration_s=duration))
    action('SetMode',{'mode':'MANUAL' if kind=='plane' else 'GUIDED'});action('Arm')
    if kind in ('copter','plane'):action('Takeoff',{'height_m':50 if kind=='plane' else 1.5})
    if kind=='plane':
        action('GetVehicleState',output='flight')
        action('SetGuidedTarget',{'latitude_deg':{'$query':dict(source='world',path='vehicle.global_position.value.latitude_deg',frame='earth',max_age_s=3,offset=math.degrees(150/6378137.))},
            'longitude_deg':{'$query':dict(source='world',path='vehicle.global_position.value.longitude_deg',frame='earth',max_age_s=3)},'altitude_amsl_m':634.})
        wait(90);action('Loiter');wait(5);action('RTL');wait(5);action('AutoLand')
    else:
        action('Goto',dict(x_m=2.,y_m=1.,z_m=0. if kind=='rover' else 1.5))
        identifier='observed';children.append(identifier)
        nodes.append(dict(id=identifier,type='Condition',expression=dict(op='eq',source='world',path='vehicle.operation.armed',value=True,max_age_s=3)))
        action('ReturnHome')
        if kind=='rover':action('Disarm')
    return dict(schema_version=1,id=kind+'-mission',name=kind+' physical Mission',version='1.0.0',target=kind,
        root='root',nodes=[dict(id='root',type='Sequence',children=children),*nodes],timeout_s=900 if kind=='plane' else 180,blackboard={})


def run(path,kind):
    f=MissionFixture(path,kind);result=dict(passed=False,kind=kind,source='real Mission HTTP / owned signed SITL / Gazebo')
    try:
        f.start();spec=build_mission(kind)
        (path/'input-mission.json').write_text(json.dumps(spec,indent=2)+'\n')
        result['validation']=f.api('/api/missions/validate',{'spec':spec})
        f.api('/api/missions/save',{'spec':spec})
        r=f.api('/api/missions/start',{'spec':spec,'allow_send':True});result['run_id']=r['id']
        result['checkpoints']={};until=time.monotonic()+(960 if kind=='plane' else 210)
        while time.monotonic()<until:
            f.truth();v=f.lab.missions.view(r['id'])
            for identifier in v['action_ids']:
                a=f.lab.runtime.view(identifier)
                if a['state']=='SUCCEEDED' and a['name'] not in result['checkpoints']:
                    t=f.truth();result['checkpoints'][a['name']]=dict(truth=[t.x_m,t.y_m,t.z_m],speed_mps=f.oracle.recent_speed_mps(),action=a)
            if v['state'] in ('SUCCEEDED','FAILED','REJECTED','CANCELLED','TIMED_OUT','UNKNOWN'):
                result['mission']=v
                if v['state']!='SUCCEEDED':raise AssertionError('Mission '+v['state']+': '+str(v['error']))
                break
            time.sleep(.05)
        else:raise TimeoutError('Mission physical scenario exceeded outer budget')
        if not v['release_safe'] or v['continuation_allowed']:raise AssertionError('completed landed Mission still owns motion')
        t=f.truth();height=t.z_m-f.initial.z_m;distance=math.hypot(t.x_m-f.initial.x_m,t.y_m-f.initial.y_m)
        if kind in ('rover','copter'):
            reached=result['checkpoints']['Goto']['truth']
            error=math.dist(reached[:2],[f.initial.x_m+2,f.initial.y_m+1])
            if error>.75:raise AssertionError('Mission Goto not corroborated by Gazebo')
            if distance>.75:raise AssertionError('Mission ReturnHome not corroborated by Gazebo')
            if kind=='copter' and (height>.2 or result['checkpoints']['Takeoff']['truth'][2]-f.initial.z_m<1.15):raise AssertionError('Mission climb or landing Gazebo mismatch')
            if (f.oracle.recent_speed_mps() or 0)>(.1 if kind=='rover' else .15):raise AssertionError('Mission physical stop not established')
            result['physical']=dict(goto_error_m=error,home_error_m=distance,ground_height_m=height,final_speed_mps=f.oracle.recent_speed_mps())
        else:
            takeoff=result['checkpoints']['Takeoff']['truth'][2]-f.initial.z_m
            rollout=[p for p in f.trajectory if p['position'][2]-f.initial.z_m<1 and (p['speed'] or 0)>8]
            if takeoff<45 or not rollout or max(math.hypot(p['position'][0]-f.initial.x_m,p['position'][1]-f.initial.y_m) for p in rollout)<10:raise AssertionError('Mission native takeoff lacked physical rollout/climb')
            if height>.25 or f.oracle.recent_speed_mps()>=1 or distance>80 or abs(t.y_m-f.initial.y_m)>15:raise AssertionError('Mission native AUTOLAND outside unchanged runway limits')
            result['physical']=dict(takeoff_height_m=takeoff,ground_rollout_samples=len(rollout),landing_home_error_m=distance,landing_height_m=height,landing_speed_mps=f.oracle.recent_speed_mps())
            for name in ('SetGuidedTarget','Loiter','RTL'):
                if result['checkpoints'][name]['action']['result']['physical_arrival_claim']:raise AssertionError('configuration falsely claimed arrival')
        result.update(passed=True,writer_calls=len(f.writer),writer=f.writer,final_state=f.api('/api/studio/state'))
    except Exception as exc:
        result['error']=type(exc).__name__+': '+str(exc)
        if f.lab:result['actions']=f.lab.runtime.views();result['missions']=f.lab.missions.views();result['driver_info']=f.driver.info()
        raise
    finally:
        try:f.close()
        finally:(path/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kind',choices=('rover','copter','plane'),required=True);p.add_argument('--run-dir',type=Path,required=True)
    a=p.parse_args();install_signal_cleanup();r=run(a.run_dir.resolve(),a.kind);print(a.kind,'Mission',r['passed'],flush=True)
if __name__=='__main__':main()
