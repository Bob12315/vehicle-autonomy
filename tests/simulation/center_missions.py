"""Real HTTP Mission terminal states on one owned SEND-off Rover SITL."""
import argparse
import json
from pathlib import Path
from threading import Thread
import time
from urllib.request import Request,urlopen
from uuid import uuid4
from vehicle_autonomy.app.web.mission_control import MissionControl,MissionControlServer
from vehicle_autonomy.app.web.server import load_token
from tests.simulation.launch import install_signal_cleanup


def run(directory):
    directory=directory.resolve();directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    token_path=directory/'web-token.private';token=load_token(token_path)
    app=MissionControl({},directory/'application');server=MissionControlServer(('127.0.0.1',0),app,token,directory/'http-audit.jsonl')
    thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.1},daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_address[1]);result=dict(status='FAIL',cases={})
    def api(path,payload=None):
        headers={'Authorization':'Bearer '+token};data=None
        if payload is not None:
            data=json.dumps(payload).encode();headers.update({'Content-Type':'application/json','X-VAF-CSRF':token,'X-VAF-Request-ID':uuid4().hex})
        with urlopen(Request(base+path,data,headers),timeout=10) as reply:value=json.load(reply)
        assert value['ok'],value
        return value['result']
    def finish(identifier,expected):
        end=time.monotonic()+8
        while time.monotonic()<end:
            value=next(m for m in api('/api/studio/state')['missions'] if m['id']==identifier)
            if value['state'] in ('SUCCEEDED','FAILED','TIMED_OUT','CANCELLED','REJECTED','UNKNOWN'):
                assert value['state']==expected and value['release_safe'],value
                return value
            time.sleep(.05)
        raise TimeoutError('Mission terminal feedback')
    try:
        session=api('/api/simulation/create',dict(scene_id='R01',vehicle='rover',parameters={'obstacle_count':0}))
        api('/api/simulation/start',dict(id=session['id']));ready=app.simulation_manager.wait_ready(session['id'],140)
        target=ready['target']
        def start(name,nodes,timeout=10,**fields):
            spec=dict(schema_version=1,id=name,name=name,version='1.0.0',target=target,root='root',nodes=nodes,timeout_s=timeout,**fields)
            return api('/api/missions/start',dict(spec=spec,allow_send=False))
        value=start('query',[dict(id='root',type='Action',action='GetVehicleState',parameters={})])
        result['cases']['normal']=finish(value['id'],'SUCCEEDED')
        value=start('false-condition',[dict(id='root',type='Condition',expression=dict(op='eq',source='blackboard',path='ready',value=True))],blackboard={'ready':False})
        result['cases']['failure']=finish(value['id'],'FAILED')
        value=start('cancel-wait',[dict(id='root',type='Wait',duration_s=5)])
        api('/api/missions/cancel',dict(id=value['id']));result['cases']['cancel']=finish(value['id'],'CANCELLED')
        value=start('deadline',[dict(id='root',type='Sequence',children=['one','two']),dict(id='one',type='Wait',duration_s=.15),dict(id='two',type='Wait',duration_s=.15)],timeout=.2)
        result['cases']['timeout']=finish(value['id'],'TIMED_OUT')
        info=app.drivers[target].info();assert not info['system_send'] and not info['action_send'] and not info['lease_active']
        result.update(status='PASS',scope='real HTTP Mission lifecycle; Query/Condition/Wait only, no motion',send=dict(system=False,action=False))
    except Exception as exc:result['error']=type(exc).__name__+': '+str(exc)
    finally:
        server.shutdown();server.server_close();thread.join(3)
        try:app.close()
        except Exception as exc:result['cleanup_error']=str(exc);result['status']='FAIL'
        token_path.unlink(missing_ok=True)
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True)
    args=p.parse_args();install_signal_cleanup();result=run(args.run_dir)
    print(json.dumps(dict(status=result['status'],cases={k:v['state'] for k,v in result['cases'].items()},error=result.get('error')),ensure_ascii=False))
    return int(result['status']!='PASS')


if __name__=='__main__':raise SystemExit(main())
