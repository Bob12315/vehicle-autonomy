"""Native fixed-library pairing acceptance through original authenticated Actions."""
import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
from threading import Thread
import time
import traceback
from urllib.request import Request,urlopen
from uuid import uuid4

from tests.simulation.web_controls import ControlCheck
from vehicle_autonomy.app.web.mission_control import MissionControl,MissionControlServer
from vehicle_autonomy.app.web.server import load_token


def run(directory,scene,kind):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    token=load_token(directory/'web-token.private')
    app=MissionControl({},directory/'application',simulation_allow_send=True)
    server=MissionControlServer(('127.0.0.1',0),app,token,directory/'http.jsonl')
    Thread(target=server.serve_forever,kwargs={'poll_interval':.1},daemon=True).start()
    base='http://127.0.0.1:'+str(server.server_address[1])
    result=dict(scene_id=scene,kind=kind,status='FAIL',checks={},error=None)
    def api(path,payload=None):
        headers={'Authorization':'Bearer '+token}
        data=None
        if payload is not None:
            data=json.dumps(payload).encode();headers.update({'Content-Type':'application/json','X-VAF-CSRF':token,'X-VAF-Request-ID':uuid4().hex})
        with urlopen(Request(base+path,data,headers),timeout=15) as response:value=json.load(response)
        if not value.get('ok'):raise AssertionError(value)
        return value['result']
    try:
        r=api('/api/simulation/create',dict(scene_id=scene,vehicle=kind,parameters={'obstacle_count':0}))
        identifier=result['id']=r['id']
        api('/api/simulation/start',{'id':identifier})
        r=app.simulation_manager.wait_ready(identifier,150)
        owner=app.simulation_manager.owners[identifier];child=next(iter(owner.vehicles.values()))
        result['vehicle']=child.view()
        assert all(child.stages.values()),child.stages
        os.environ.update(GZ_IP='127.0.0.1',GZ_PARTITION=owner.partition)
        from tests.simulation.oracle import GazeboTruthOracle
        oracle=GazeboTruthOracle(owner.world,child.model.name)
        until=time.monotonic()+45
        while time.monotonic()<until:
            if app.simulation_manager.sample(identifier)['state']=='FAILED':raise AssertionError(app.simulation_manager.sample(identifier)['error'])
            time.sleep(.2)
        check=ControlCheck(kind,api,oracle,directory,target=child.target,expected_system_id=child.model.system_id)
        if kind=='plane':result['physical']=check.run()
        else:
            try:
                check.information('initialized',armed=False)
                check.perform('SetMode',{'mode':'GUIDED'})
                check.perform('Arm')
                if kind=='rover':
                    check.managed('Drive',dict(speed_mps=.3,yaw_rate_rad_s=0),('distance',.5))
                    check.perform('Disarm')
                    check.information('motion stopped',armed=False)
                    assert oracle.recent_speed_mps()<.1
                else:
                    check.perform('Takeoff',{'height_m':1.5},45)
                    check.information('airborne',armed=True)
                    assert abs(check.truth().z_m-check.initial.z_m-1.5)<.35
                    check.perform('Goto',dict(x_m=1.5,y_m=0,z_m=1.5),55)
                    check.perform('ReturnHome',seconds=70)
                    check.information('landed',armed=False)
                    assert oracle.recent_speed_mps()<.15
                check.result['passed']=True
                result['physical']=check.result
            finally:check.save();check.trace.close();check.trajectory.close()
        result['checks'].update(world_entity_plugin_sitl_framework='PASS',basic_motion_and_safe_exit='PASS')
        api('/api/simulation/stop',{'id':identifier})
        app.simulation_manager.threads[identifier].join(70)
        r=app.simulation_manager.sample(identifier)
        assert r['state']=='FINISHED' and r['cleanup']=='COMPLETE',r.get('error')
        assert child.session.manifest.get('credentials_removed') is True
        result['cleanup']=r['cleanup'];result['metrics']=r['metrics'];result['status']='PASS'
    except Exception as exc:
        result['error']=type(exc).__name__+': '+str(exc)
        traceback.print_exc()
    finally:
        server.shutdown();server.server_close();app.close()
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(scene,kind,result['status'],result.get('error'),flush=True)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('scene');p.add_argument('kind');args=p.parse_args()
    raise SystemExit(0 if run(args.directory,args.scene,args.kind)['status']=='PASS' else 1)
