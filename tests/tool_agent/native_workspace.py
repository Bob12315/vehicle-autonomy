"""Workspace integration with actual installed Gazebo/ROS/RViz software."""
import argparse
import json
from pathlib import Path

from .helpers import CTX,wait
from .test_service import Harness
from .test_workspaces import component,spec


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--registry',type=Path,required=True);p.add_argument('--run-dir',type=Path,required=True)
    a=p.parse_args();root=a.run_dir;root.mkdir(parents=True,exist_ok=False,mode=0o700)
    h=Harness(root,json.loads(a.registry.read_text())['tools']);report=dict(passed=False,source='actual Gazebo stats + ROS graph + RViz process; no vehicle/sensor input or mocks')
    try:
        value=spec('native-lab',components=[component('gazebo',profile_id='headless',timeout_s=40),component('ros2',['gazebo'],timeout_s=20),component('rviz2',['ros2'],optional=True,timeout_s=5)])
        assert h.api('/api/workspaces/save',dict(spec=value))[0]==200
        code,result=h.api('/api/workspaces/launch',dict(id=value['id']));assert code==200,result
        run_id=result['result']['id']
        def prepared():
            run=h.service.workspaces.data['runs'][run_id]
            return run if run['state'] in ('READY','DEGRADED','FAILED') else None
        run=wait(prepared,80);report['prepared']=json.loads(json.dumps(run))
        assert run['state']=='DEGRADED',run
        assert run['components'][0]['state']=='READY' and run['components'][1]['state']=='READY'
        assert run['components'][2]['state']=='SKIPPED' and not run['components'][2]['observed_ready']
        code,result=h.api('/api/workspaces/stop',dict(run_id=run_id));assert code==200,result
        wait(lambda:run['state']=='STOPPED',35)
        report.update(passed=True,stopped=json.loads(json.dumps(run)),instances=h.local.snapshot())
        assert all(not i['process_running'] and i['cleanup_confirmed'] for i in h.local.instances.values())
    finally:
        h.close();(root/'summary.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(passed=report['passed'],state=report.get('prepared',{}).get('state'),actual_tools=list(h.local.instances))))


if __name__=='__main__':main()
