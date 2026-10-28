"""Real Tool Workspace -> Gazebo/JSON Rover SITL; receive-only telemetry check."""
import argparse
import json
from pathlib import Path
import socket
import time

from .helpers import wait
from .test_service import Harness
from .test_workspaces import component,spec


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--registry',required=True,type=Path);p.add_argument('--run-dir',required=True,type=Path)
    a=p.parse_args();a.run_dir.mkdir(parents=True,exist_ok=False,mode=0o700)
    h=Harness(a.run_dir,json.loads(a.registry.read_text())['tools']);report=dict(passed=False,source='actual coupled Gazebo ArduPilot plugin + JSON Rover SITL; no control writes')
    try:
        value=spec('coupled-rover',components=[component('gazebo',profile_id='rover-coupled',wait_for='running',timeout_s=50),component('sitl',['gazebo'],profile_id='rover-coupled',timeout_s=50)])
        assert h.api('/api/workspaces/save',dict(spec=value))[0]==200
        code,body=h.api('/api/workspaces/launch',dict(id=value['id']));assert code==200,body
        run=h.service.workspaces.data['runs'][body['result']['id']]
        wait(lambda:run['state'] in ('READY','FAILED'),70);report['prepared']=json.loads(json.dumps(run));assert run['state']=='READY',run
        from pymavlink.dialects.v20 import ardupilotmega as mav
        parser=mav.MAVLink(None);parser.robust_parsing=True;types=set();heartbeat=None
        with socket.create_connection(('127.0.0.1',6460),timeout=2) as connection:
            end=time.monotonic()+12
            while time.monotonic()<end:
                for message in parser.parse_buffer(connection.recv(65536)) or []:
                    if message.get_type()=='BAD_DATA':continue
                    types.add(message.get_type())
                    if message.get_type()=='HEARTBEAT':
                        heartbeat=message.to_dict();assert message.type==10 and not message.base_mode&128
                if heartbeat and {'ATTITUDE','GLOBAL_POSITION_INT'}<=types:break
        assert heartbeat and {'ATTITUDE','GLOBAL_POSITION_INT'}<=types,types
        report.update(heartbeat=heartbeat,received_types=sorted(types),vehicle_writes=0)
        assert h.api('/api/workspaces/stop',dict(run_id=run['id']))[0]==200
        wait(lambda:run['state']=='STOPPED',30)
        report.update(passed=True,cleaned=all(v['cleanup_confirmed'] and not v['process_running'] for v in h.local.instances.values()))
    finally:
        report['instances']=h.local.snapshot();h.close();(a.run_dir/'summary.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('passed','cleaned','vehicle_writes','received_types')}))


if __name__=='__main__':main()
