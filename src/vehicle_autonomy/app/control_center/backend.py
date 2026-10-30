"""Dedicated systemd main process; all simulators/tools inherit its cgroup."""
import argparse
import json
import os
from pathlib import Path
import signal
from threading import Event,Thread
import time
from uuid import uuid4

from vehicle_autonomy.app.web.mission_control import MissionControl,MissionControlServer
from vehicle_autonomy.app.web.server import load_token
from vehicle_autonomy.app.web.passwords import load_password
from vehicle_autonomy.app.tools.service import ToolService
from .service import ControlCenter
from .supervisor import atomic,lock_workspace,process_identity,unit_name


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',type=Path,required=True);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--parent-pid',type=int,required=True);parser.add_argument('--parent-ticks',required=True)
    parser.add_argument('--port',type=int,default=8780);parser.add_argument('--allow-send',action='store_true');parser.add_argument('--config',type=Path)
    args=parser.parse_args();root=args.root.resolve();directory=args.run_dir.resolve()
    cgroup=Path('/proc/self/cgroup').read_text().strip().split('::',1)[-1]
    if not cgroup.endswith('/'+unit_name(root)):raise ValueError('必须经 ./control-center 的独立 systemd 用户服务启动；拒绝无 OS 清理保障的后台。')
    lock=lock_workspace(root,'backend');stop=Event();app=server=center=tools=None;http_thread=None;errors=[]
    state=dict(session_id='center-'+uuid4().hex,state='STARTING',pid=os.getpid(),cgroup=cgroup,unit=unit_name(root),
        url=f'http://127.0.0.1:{args.port}/center',token_file=str(root/'runtime/control-center/operator.private'),
        authentication='password',password_file=str(root/'runtime/control-center/password.json'),
        logs=str(directory),deployment_send=args.allow_send,system_send=False,action_send=False,started_at=time.time())
    atomic(directory/'state.json',state)
    os.environ['VAF_CONTROL_CENTER_SESSION']=state['session_id']
    parent=root/'runtime/control-center';parent.mkdir(mode=0o700,exist_ok=True)
    atomic(parent/'current.json',dict(run_dir=str(directory),**state))
    signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
    try:
        # Loopback listener binds before any optional services may start.
        token=load_token(state['token_file']);feed=directory/'visualization.private';load_token(feed)
        source=directory/'visualization-source.json'
        atomic(source,dict(schema=1,url=f'http://127.0.0.1:{args.port}',token_file=str(feed),use_sim_time=False))
        app=MissionControl({},directory/'application',simulation_allow_send=args.allow_send)
        tools=ToolService(directory/'remote-tools');app.tool_service=tools
        server=MissionControlServer(('127.0.0.1',args.port),app,token,directory/'http-audit.jsonl');server.visualization_token=load_token(feed)
        server.password_auth=load_password(state['password_file'])
        center=ControlCenter(app,root,directory,state['session_id'],source,stop,cgroup,args.config);app.control_center=center
        http_thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.1},daemon=True);http_thread.start()
        state['availability']=dict(tools=center.host['tools'],desktop=center.host['desktop'],ros_error=center.host['ros_error'],
            vehicles=[{k:v.get(k) for k in ('id','status','reason','binary','fingerprint')} for v in app.simulation_manager.vehicle_registry.list_vehicles()])
        state['state']='READY';atomic(directory/'state.json',state);atomic(parent/'current.json',dict(run_dir=str(directory),**state))
        print('READY '+state['url']+' · session '+state['session_id'],flush=True)
        while not stop.wait(.5):
            try:alive=process_identity(args.parent_pid)==args.parent_ticks
            except OSError:alive=False
            if not alive:
                print('Launcher ended; closing owned deployment.',flush=True);stop.set()
    except Exception as exc:
        state.update(state='FAILED',error=type(exc).__name__+': '+str(exc));errors.append(state['error']);raise
    finally:
        state['state']='STOPPING';atomic(directory/'state.json',state)
        # Stop accepting new ingress before original Runtime shutdown. Existing
        # cancellation/physical uncertainty rules remain authoritative.
        if server:
            if http_thread:server.shutdown();http_thread.join(3)
            server.server_close()
        # Existing SimulationManager owns Driver/SITL/World shutdown. Graphical
        # clients follow afterwards; systemd is the final cgroup cleanup owner.
        for label,owner in (('framework',app),('desktop-tools',center),('remote-tools',tools)):
            if owner:
                try:owner.close()
                except Exception as exc:errors.append(label+': '+str(exc));print(errors[-1],flush=True)
        (directory/'visualization.private').unlink(missing_ok=True)
        state.update(state='FAILED' if errors else 'STOPPED',ended_at=time.time(),cleanup_errors=errors)
        atomic(directory/'state.json',state);atomic(parent/'current.json',dict(run_dir=str(directory),**state));lock.close()
    return 1 if errors else 0


if __name__=='__main__':raise SystemExit(main())
