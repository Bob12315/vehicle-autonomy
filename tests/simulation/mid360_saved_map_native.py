"""Fresh desktop verification of persisted PCDs, with no simulator or LIO."""
import argparse, hashlib, json, time, traceback
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.simulation.mid360_tools import Mid360Tools
from vehicle_autonomy.app.simulation.mid360_slam import Mid360Slam
from tests.visualization.desktop import goal


def run(directory, references):
    directory=directory.resolve();directory.mkdir(parents=True,exist_ok=False)
    report=dict(status='FAIL',maps=[])
    try:
        for reference in references:
            old=json.loads((reference/'slam-result.json').read_text())
            sources=list((reference/'application/simulation').glob('sim-*/vehicle-*/mid360/source.json'))
            assert len(sources)==1,sources
            config=json.loads(sources[0].read_text());kind=config['kind']
            child=SimpleNamespace(directory=directory/kind,id='vehicle-'+uuid4().hex,target='saved-map-only',
                owner=SimpleNamespace(root=resource_root(),partition='saved-map-'+uuid4().hex))
            child.directory.mkdir()
            parent=Mid360Tools(child,config,archive=True);service=Mid360Slam(parent);parent.slam=service
            try:
                service.load(old['map']['id']);service.rviz(loaded=True)
                deadline=time.monotonic()+100
                while not parent.snapshot()['tools']['slam-rviz']['ready']:
                    assert time.monotonic()<deadline,parent.snapshot()
                    time.sleep(.2)
                pid=parent.tools.instances['slam-rviz']['pid']
                goal(pid,select=False);time.sleep(3)
                capture=directory/(kind+'-loaded-map.png');window=goal(pid,capture=capture,select=False)
                view=json.loads(next(parent.directory.glob('view-health-*.json')).read_text())
                assert view['status']=='READY',view
                assert not service.started_at and not parent._active('fast-lio') and not parent._active('mid360')
                rviz=(parent.directory/'slam-view.rviz').read_text()
                assert rviz.count('Class: rviz_default_plugins/PointCloud2')==1 and 'loaded_map' in rviz
                report['maps'].append(dict(kind=kind,map_id=old['map']['id'],probe=view,window=window,
                    screenshot=str(capture),screenshot_sha256=hashlib.sha256(capture.read_bytes()).hexdigest(),
                    context=parent._ctx('map'),status='PASS'))
            finally:parent.close()
        report['status']='PASS'
    except Exception:report['error']=traceback.format_exc()
    (directory/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status'],flush=True);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True,type=Path)
    parser.add_argument('--reference-run',required=True,action='append',type=Path);args=parser.parse_args()
    raise SystemExit(0 if run(args.run_dir,args.reference_run)['status']=='PASS' else 1)
