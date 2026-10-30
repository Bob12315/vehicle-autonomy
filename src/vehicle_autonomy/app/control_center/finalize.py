"""systemd ExecStopPost: record kernel cleanup and destroy only owned secrets.

This hook runs after systemd stops the service cgroup, including after SIGKILL.
It never adopts/signals persisted PIDs, never grants physical stop confirmation,
and reuses the inode-checked existing credential destruction contract.
"""
import argparse
import json
import os
from pathlib import Path
import time

from vehicle_autonomy.app.bootstrap.simulation_credentials import OwnedCredentials
from .supervisor import atomic,process_table


def finalize(root,directory):
    root=Path(root).resolve();directory=Path(directory)
    if directory.resolve()!=directory or directory.parent!=root/'runtime/control-center' or not directory.name.startswith('cc-'):
        raise ValueError('unowned Control Center finalizer directory')
    path=directory/'state.json'
    if not path.exists():return
    state=json.loads(path.read_text());records=process_table(state['cgroup'])
    remaining=[r for r in records if r['pid']!=os.getpid()]
    result=dict(service_result=os.environ.get('SERVICE_RESULT'),exit_code=os.environ.get('EXIT_CODE'),
        exit_status=os.environ.get('EXIT_STATUS'),remaining_owned_processes=remaining,credential_errors=[],finished_at=time.time())
    # Cleanup metadata is written even when normal Python finally never ran.
    if not remaining:
        for manifest_path in sorted((directory/'application/simulation').glob('*/vehicle-*/session.json')):
            try:
                if manifest_path.resolve()!=manifest_path:raise ValueError('symlinked vehicle state refused')
                manifest=json.loads(manifest_path.read_text())
                if manifest.get('framework_runtime') and not manifest.get('credentials_removed'):
                    OwnedCredentials(manifest_path.parent,manifest).destroy()
                    manifest.update(control_center_os_cleanup=True,physical_stop='UNCONFIRMED')
                    atomic(manifest_path,manifest)
            except Exception as exc:result['credential_errors'].append(str(manifest_path)+': '+str(exc))
        (directory/'visualization.private').unlink(missing_ok=True)
    abnormal=state['state'] not in ('STOPPED','FAILED')
    if abnormal:state.update(state='CRASHED',physical_stop='UNCONFIRMED',ended_at=time.time())
    state['os_cleanup']=result;atomic(path,state)
    current=root/'runtime/control-center/current.json'
    if current.exists() and json.loads(current.read_text()).get('session_id')==state['session_id']:
        atomic(current,dict(run_dir=str(directory),**state))
    atomic(directory/'os-cleanup.json',result)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args();finalize(args.root,args.run_dir)


if __name__=='__main__':main()
