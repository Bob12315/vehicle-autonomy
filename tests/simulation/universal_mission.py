"""Native multi-target query Missions through the unchanged Mission runtime."""
import argparse
import json
from pathlib import Path
import time
import traceback
from vehicle_autonomy.app.web.mission_control import MissionControl


def run(directory):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    app=MissionControl({},directory/'application')
    manager=app.simulation_manager
    result=dict(status='FAIL',missions=[],allow_send=False)
    try:
        session=manager.create(dict(scene_id='R01',vehicles=[dict(kind='rover',spawn={'id':'center'}),
            dict(kind='copter',spawn={'id':'north'})],parameters={'obstacle_count':0}))
        manager.start(session['id']);session=manager.wait_ready(session['id'],150)
        for vehicle in session['vehicles']:
            spec=dict(schema_version=1,id='query-'+vehicle['id'],name='独立仿真状态查询',version='1.0.0',
                target=vehicle['target'],root='query',timeout_s=10,
                nodes=[dict(id='query',type='Action',action='GetVehicleState',parameters={})])
            mission=app.handle('mission.start',dict(spec=spec,allow_send=False))
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                current=next(m for m in app.missions.views() if m['id']==mission['id'])
                if current['state'] in {'SUCCEEDED','FAILED','UNKNOWN','REJECTED','CANCELLED','TIMED_OUT'}:break
                time.sleep(.05)
            assert current['state']=='SUCCEEDED' and current['release_safe'],current
            driver=app.drivers[vehicle['target']]
            info=driver.info();assert info['connected'] and not info['system_send'] and not info['action_send']
            result['missions'].append(dict(vehicle_id=vehicle['id'],kind=vehicle['kind'],target=vehicle['target'],mission=current))
        result['status']='PASS'
    except Exception as exc:result['error']=type(exc).__name__+': '+str(exc);traceback.print_exc()
    finally:
        try:app.close()
        except Exception as exc:result['cleanup_error']=str(exc);result['status']='FAIL'
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(result['status'],result.get('error'),flush=True)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');a=p.parse_args()
    raise SystemExit(run(a.directory)['status']!='PASS')
