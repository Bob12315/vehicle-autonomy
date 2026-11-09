"""Actual sliced Gazebo sensor qualification, not SLAM or precision acceptance."""
import argparse,json,traceback
from pathlib import Path
from tests.simulation.control_binding_native import Native


def run(path):
    n=Native(path);result=dict(status='FAIL',scope='sensor timing stage only')
    try:
        r=n.api('/api/simulation/create',dict(scene_id='L01',vehicles=[
            dict(kind=k,spawn={'id':spawn},sensors={'mid360':True,'mid360_lio':True})
            for k,spawn in (('rover','center'),('copter','north'))],parameters={'obstacle_count':0}))
        n.api('/api/simulation/start',{'id':r['id']});n.app.simulation_manager.wait_ready(r['id'],180)
        owner=n.app.simulation_manager.owners[r['id']];result['sensors']={};domains=[]
        for child in owner.vehicles.values():
            state=n.wait(lambda:(s if (s:=child.mid360.snapshot())['online'] else None),60)
            state=n.wait(lambda:(s if (s:=child.mid360.snapshot())['health'].get('capture_trace') else None),10)
            cloud=state['health']['cloud'];trace=state['health']['capture_trace']
            offsets=[t-trace['timebase_ns'] for t in trace['capture_times_ns']]
            assert len(offsets)==5 and offsets[0]==0 and 70_000_000<=offsets[-1]<=100_000_000,trace
            assert set(cloud['capture_offsets_ns'])<=set(offsets) and sum(trace['return_counts'])==cloud['points'],(cloud,trace)
            assert cloud['points']>1000 and cloud['timing']=='five_actual_Gazebo_render_capture_times_per_frame',cloud
            domains.append(state['domains']['live']);result['sensors'][child.vehicle]=state
        assert len(set(domains))==2
        result['status']='PASS';n.report['status']='PASS'
    except Exception:result['error']=traceback.format_exc();print(result['error'],flush=True)
    finally:
        n.close();result['cleanup']=n.report['cleanup']
        if n.report.get('cleanup_error'):result.update(status='FAIL',cleanup_error=n.report['cleanup_error'])
        (Path(path)/'sensor-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(result['status'],flush=True);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True,type=Path);a=parser.parse_args()
    raise SystemExit(0 if run(a.run_dir)['status']=='PASS' else 1)
