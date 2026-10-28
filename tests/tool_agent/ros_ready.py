"""Actual native ROS/Nav2/RViz readiness using explicitly synthetic ROS inputs."""
import argparse
import json
from pathlib import Path
import sys

from .helpers import CTX,tool,wait
from .test_service import Harness
from .test_workspaces import component,spec


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--registry',type=Path,required=True);p.add_argument('--run-dir',type=Path,required=True)
    a=p.parse_args();a.run_dir.mkdir(parents=True,exist_ok=False,mode=0o700)
    tools=json.loads(a.registry.read_text())['tools'];nav2=next(t for t in tools if t['id']=='nav2')
    fixture=tool('data-fixture',ready=False);fixture['profiles']['default']['argv']=[sys.executable,'-u','-m','tests.tool_agent.ros_fixture']
    fixture['profiles']['default']['env']=nav2['profiles']['default']['env'];tools.append(fixture)
    # The launched fixture module belongs only to this test source tree. It is
    # explicitly passed on PYTHONPATH, never added to installed production Tools.
    fixture['profiles']['default']['env']=dict(fixture['profiles']['default']['env'],PYTHONPATH=str(Path(__file__).resolve().parents[2])+':'+fixture['profiles']['default']['env'].get('PYTHONPATH',''))
    h=Harness(a.run_dir,tools);report=dict(passed=False,source='actual native ROS/Nav2/RViz executables with synthetic map/TF/scan/odom; no real sensors or vehicle',vehicle_writes=0,navigation_goals=0)
    try:
        value=spec('ros-readiness',components=[component('data-fixture',wait_for='running'),component('ros2',['data-fixture'],timeout_s=30),component('nav2',['ros2'],timeout_s=150),component('rviz2',['ros2'],timeout_s=80)])
        assert h.api('/api/workspaces/save',dict(spec=value))[0]==200
        code,result=h.api('/api/workspaces/launch',dict(id=value['id']));assert code==200,result
        run=h.service.workspaces.data['runs'][result['result']['id']]
        def done():
            # The synthetic publisher intentionally has no functional probe;
            # PREPARED is correct if all native components are actually Ready.
            return run['state'] in ('PREPARED','READY','FAILED')
        wait(done,170);report['run']=json.loads(json.dumps(run));report['tools']=h.local.snapshot()
        by_id={c['id']:c for c in run['components']}
        assert run['state'] in ('READY','PREPARED'),run
        assert all(by_id[name]['observed_ready'] for name in ('ros2','nav2','rviz2')),run
        assert h.api('/api/workspaces/stop',dict(run_id=run['id']))[0]==200
        wait(lambda:run['state']=='STOPPED',35)
        report.update(passed=True,cleanup_confirmed=all(v['cleanup_confirmed'] and not v['process_running'] for v in h.local.instances.values()))
    finally:
        report['final_tools']=h.local.snapshot();h.close();(a.run_dir/'summary.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('passed','cleanup_confirmed','source','vehicle_writes','navigation_goals')}))


if __name__=='__main__':main()
