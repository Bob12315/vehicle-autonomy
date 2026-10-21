"""Owned read-only application + console supervisor, without system-service changes."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
import urllib.request

from app.control import request
from deployment.hardware_profile import load_profile
from web_ui.server import load_token

ROOT=Path(__file__).resolve().parents[1]


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def cleanup_previous_boot_socket(directory):
    """Only reclaim our recorded inode from a demonstrably earlier boot."""
    try:
        value=json.loads((directory/'supervisor.json').read_text())
        path=directory/'app.sock'
        info=path.lstat()
        if (value.get('boot_id') and value['boot_id']!=boot_id()
                and value.get('socket_inode')==info.st_ino
                and stat.S_ISSOCK(info.st_mode) and info.st_uid==os.getuid()):
            path.unlink()
    except FileNotFoundError:
        pass


def process_identity(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]
    except FileNotFoundError:
        return None


def metadata(path, value):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value));temporary.replace(path)


def owned_supervisor(directory):
    try:
        value=json.loads((directory/'supervisor.json').read_text())
        if value.get('boot_id') and value['boot_id']!=boot_id():
            return None
        if process_identity(value['pid'])!=value['start_ticks']:
            return None
        command=Path(f"/proc/{value['pid']}/cmdline").read_bytes().split(b'\0')
        if b'deployment.onboard' not in command or b'supervise' not in command:
            raise ValueError('supervisor identity mismatch; no signal sent')
        return value
    except FileNotFoundError:
        return None


def supervise(args,directory):
    profile=load_profile(args.config)
    if profile['mode']!='hardware_readonly':
        raise ValueError('supervisor supports hardware_readonly only')
    lock=(directory/'owner.lock').open('a')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise ValueError('an onboard supervisor already owns this directory')
    cleanup_previous_boot_socket(directory)
    children=[]
    handles=[]
    stopping=False
    socket_identity=None
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    owner={'pid':os.getpid(),'start_ticks':process_identity(os.getpid()),'boot_id':boot_id(),
        'source_root':str(ROOT),'mode':'hardware_readonly','port':args.port}
    metadata(directory/'supervisor.json',owner)
    env=dict(os.environ)
    env['PYTHONPATH']=str(ROOT)+(os.pathsep+env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    commands=[]
    expected_epoch=[]
    if args.rs16_config:
        from deployment.rs16_profile import sensor_commands
        commands.extend(sensor_commands(args.rs16_config,profile,ROOT,ros=args.ros2_humble))
        expected_epoch=['--expected-lidar-epoch',commands[0][1][-1]]
    commands.extend([('application',[sys.executable,'-m','app.hardware','--config',str(Path(args.config).resolve()),
        '--control-socket',str(directory/'app.sock'),'--log-dir',str(directory/'logs'),*expected_epoch]),
        ('web',[sys.executable,'-m','app.web','--control-socket',str(directory/'app.sock'),
        '--token-file',str(directory/'token'),'--data-dir',str(directory/'console'),'--port',str(args.port),
        *(['--llm-config',str(Path(args.llm_config).resolve())] if args.llm_config else [])])])
    result={'passed':False,'mode':'hardware_readonly','physical_stop':'UNCONFIRMED'}
    try:
        load_token(directory/'token')
        for name,command in commands:
            handle=(directory/(name+'.stderr.log')).open('ab');handles.append(handle)
            child=subprocess.Popen(command,cwd=ROOT,env=env,stdout=handle,stderr=handle,start_new_session=True)
            children.append((name,child))
        metadata(directory/'children.json',[{'name':name,'pid':child.pid,'start_ticks':process_identity(child.pid)} for name,child in children])
        while not stopping:
            if socket_identity is None:
                try:
                    info=(directory/'app.sock').lstat()
                    if stat.S_ISSOCK(info.st_mode) and info.st_uid==os.getuid():
                        socket_identity=info.st_ino
                        metadata(directory/'supervisor.json',{**owner,'socket_inode':socket_identity})
                except FileNotFoundError:pass
            for name,child in children:
                if child.poll() is not None:
                    raise RuntimeError(f'{name} exited {child.returncode}; read-only stack stopped, explicit restart required')
                if (directory/(name+'.stderr.log')).stat().st_size>4_000_000:
                    raise RuntimeError(f'{name} stderr log budget reached')
            time.sleep(.2)
        result['passed']=True
    except Exception as exc:
        result['error']=f'{type(exc).__name__}: {exc}'
    finally:
        # Close console/Application and owned sensors; no child can assert physical Stop.
        for name,child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for name,child in children:
            try:child.wait(timeout=6)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=2)
                result.update(passed=False,cleanup_error=name+' exceeded shutdown deadline')
        for handle in handles:handle.close()
        # SIGKILL cannot run the Application's finally block. Only remove the
        # exact private socket observed while our own child was alive.
        if socket_identity is not None:
            try:
                if (directory/'app.sock').lstat().st_ino==socket_identity:
                    (directory/'app.sock').unlink()
            except FileNotFoundError:pass
        metadata(directory/'last-stop.json',result)
        (directory/'supervisor.json').unlink(missing_ok=True)
        lock.close()
    return 0 if result['passed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('start','stop','status','supervise'))
    parser.add_argument('--state-dir',default=str(Path.home()/'.local/state/vehicle-autonomy'))
    parser.add_argument('--config',default=str(ROOT/'config/deployment/hardware-readonly.json'))
    parser.add_argument('--llm-config')
    parser.add_argument('--rs16-config',help='explicit official SDK receiver; never configures a NIC or LiDAR')
    parser.add_argument('--ros2-humble',action='store_true',help='also supervise the isolated ARM64 ROS scan sidecar')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    if args.ros2_humble and not args.rs16_config:
        parser.error('--ros2-humble requires --rs16-config')
    directory=Path(args.state_dir).resolve();directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    info=directory.stat()
    if info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise ValueError('state directory must be private and owned (0700)')
    if len(os.fsencode(str(directory/'app.sock')))>=108:
        raise ValueError('state directory too long for AF_UNIX')
    if args.operation=='supervise':
        return supervise(args,directory)
    value=owned_supervisor(directory)
    if args.operation=='stop':
        if value:
            os.kill(value['pid'],signal.SIGTERM)
            deadline=time.monotonic()+10
            while time.monotonic()<deadline and owned_supervisor(directory):time.sleep(.1)
            if owned_supervisor(directory):raise RuntimeError('supervisor did not stop in time')
        print(json.dumps({'stopped':True,'physical_stop':'UNCONFIRMED'}));return 0
    if args.operation=='status':
        if not value:
            print(json.dumps({'running':False,'physical_stop':'UNCONFIRMED'}));return 1
        print(json.dumps(request(directory/'app.sock','status'),ensure_ascii=False));return 0
    if value:raise ValueError('already running; use status')
    load_profile(args.config)
    if args.rs16_config:
        from deployment.rs16_profile import sensor_commands
        sensor_commands(args.rs16_config,load_profile(args.config),ROOT,ros=args.ros2_humble)
    command=[sys.executable,'-m','deployment.onboard','supervise','--state-dir',str(directory),
        '--config',str(Path(args.config).resolve()),'--port',str(args.port),
        *(['--llm-config',str(Path(args.llm_config).resolve())] if args.llm_config else []),
        *(['--rs16-config',str(Path(args.rs16_config).resolve())] if args.rs16_config else []),
        *(['--ros2-humble'] if args.ros2_humble else [])]
    with (directory/'supervisor.stderr.log').open('ab') as log:
        child=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
    deadline=time.monotonic()+12
    token=None
    while time.monotonic()<deadline and child.poll() is None:
        try:
            if (directory/'token').exists():token=load_token(directory/'token')
            state=request(directory/'app.sock','status',timeout_s=.5)
            req=urllib.request.Request(f'http://127.0.0.1:{args.port}/api/status',headers={'Authorization':'Bearer '+token})
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req,timeout=1) as response:health=json.load(response)
            if health.get('ok') and state.get('ok'):
                print(json.dumps({'started':True,'mode':'hardware_readonly','url':f'http://127.0.0.1:{args.port}',
                                  'token_file':str(directory/'token')}));return 0
        except (OSError,ValueError,TypeError):pass
        time.sleep(.1)
    if child.poll() is None:child.terminate();child.wait(timeout=10)
    raise RuntimeError('read-only stack failed readiness; inspect private state logs')


if __name__=='__main__':raise SystemExit(main())
