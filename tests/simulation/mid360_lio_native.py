"""Actual LIO bring-up evidence. Does not certify trajectory accuracy or SLAM goal."""
import argparse,json,time,traceback
from pathlib import Path
from tests.simulation.control_binding_native import Native
from vehicle_autonomy.app.simulation.mid360_slam import Mid360Slam


def run(path,kind):
    n=Native(path);result=dict(status='FAIL',scope='actual LIO stationary qualification only',kind=kind)
    try:
        r=n.api('/api/simulation/create',dict(scene_id='L01',vehicles=[
            dict(kind=kind,spawn={'id':'center'},sensors={'mid360':True,'mid360_lio':True})],parameters={'obstacle_count':0}))
        n.api('/api/simulation/start',{'id':r['id']});n.app.simulation_manager.wait_ready(r['id'],180)
        owner=n.app.simulation_manager.owners[r['id']];child=next(iter(owner.vehicles.values()))
        n.wait(child.mid360.online,60)
        service=Mid360Slam(child.mid360);child.mid360.slam=service
        service.start();result['directory']=str(service.directory)
        deadline=time.monotonic()+90;records=[]
        while time.monotonic()<deadline:
            status=service.snapshot();records.append(dict(at=time.monotonic(),status=status))
            if not status['running']:break
            if status['online'] and status['state'].get('revision',0)>=30:break
            time.sleep(.25)
        (Path(path)/'lio-samples.json').write_text(json.dumps(records,indent=2)+'\n')
        result['last']=status
        assert status['online'],status
        assert status['state']['revision']>=30,status
        assert status['state']['map']['points']>=2000,status
        snapshot=service.world.reader().snapshot();assert snapshot.localization is not None,snapshot
        result['saved_map']=service.save('L01 '+kind+' stationary qualification')
        document,data=service.catalog.load(result['saved_map']['id'])
        (Path(path)/'map.pcd').write_bytes(data)
        result['map_load']=dict(points=document['points'],bytes=len(data),id=document['id'])
        result['status']='PASS';n.report['status']='PASS'
    except Exception:result['error']=traceback.format_exc();print(result['error'],flush=True)
    finally:
        n.close();result['cleanup']=n.report['cleanup']
        if n.report.get('cleanup_error'):result.update(status='FAIL',cleanup_error=n.report['cleanup_error'])
        (Path(path)/'lio-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(result['status'],flush=True);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True,type=Path)
    parser.add_argument('--kind',choices=['rover','copter'],default='rover');a=parser.parse_args()
    raise SystemExit(0 if run(a.run_dir,a.kind)['status']=='PASS' else 1)
