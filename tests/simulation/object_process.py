"""Read-only public App sensor appearance/move/disappearance acceptance."""
import argparse,json,sys,time
from pathlib import Path
from uuid import uuid4
from app.control import request
from tests.simulation.launch import ROOT,OwnedSimulation,install_signal_cleanup
from tests.simulation.object_fixture import add_objects,service
from tests.simulation.oracle import GazeboTruthOracle

def run(directory):
    directory.mkdir(parents=True,exist_ok=False);owned=OwnedSimulation(directory,'copter');report={'passed':False};log=(directory/'status.jsonl').open('w')
    try:
        sensor=add_objects(owned);owned.start()
        oracle=GazeboTruthOracle(owned.world,'target_1')
        config=directory/'profile.toml';config.write_text((ROOT/'simulation/profiles/copter.toml').read_text().replace('port = 5760',f'port = {owned.port}'))
        endpoint=directory/'app.sock';app=owned.start_process('application',[sys.executable,'-m','app.main','run','--profile','copter_sim','--config',str(config),'--control-socket',str(endpoint),'--sim-sensor-config',str(sensor)])
        def wait(predicate,timeout=30):
            until=time.monotonic()+timeout
            while time.monotonic()<until:
                owned.assert_alive()
                if endpoint.exists():
                    s=request(endpoint,'status')['result'];log.write(json.dumps(s)+'\n');log.flush()
                    assert not s['system_send'] and not s['action_send']
                    if predicate(s):return s
                time.sleep(.1)
            raise TimeoutError('object publication')
        state=wait(lambda s:len(s['objects'])==3 and s['state']=='READY')
        assert all(o['producer'].startswith('sim.objects:') and o['frame']=='odom' and o['age_ns']<3_000_000_000 for o in state['objects'])
        truth=oracle.latest();observed=next(o for o in state['objects'] if o['label']=='bucket_1')
        assert truth and abs(truth.x_m-observed['position'][0])<.02 and abs(truth.y_m-observed['position'][1])<.02
        report['appeared']=True
        service(owned,'set_pose','gz.msgs.Pose','name: "target_1" position { x: 2.5 y: 1.2 z: 0.05 } orientation { w: 1 }')
        state=wait(lambda s:any(o['label']=='bucket_1' and abs(o['position'][0]-2.5)<.02 for o in s['objects']))
        report['moved']=True
        # Oracle is a separate subscriber, and is intentionally no longer read after target removal.
        service(owned,'remove','gz.msgs.Entity','name: "target_1" type: MODEL')
        wait(lambda s:len(s['objects'])==2 and all(o['label']!='bucket_1' for o in s['objects']),6)
        report['disappeared']=True
        request(endpoint,'shutdown');assert app.wait(timeout=8)==0;owned.stop_process(app);report['passed']=True
    except Exception as exc:report['error']=f'{type(exc).__name__}: {exc}'
    finally:
        try:owned.close()
        except Exception as exc:report['cleanup_error']=str(exc);report['passed']=False
        log.close();(directory/'summary.json').write_text(json.dumps(report,indent=2))
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path);a=p.parse_args();install_signal_cleanup();r=run(a.run_dir or ROOT/'artifacts/simulation'/f'objects-{uuid4().hex[:8]}');print(json.dumps(r));return 0 if r['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
