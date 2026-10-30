"""One terminal entry; browsers are intentionally outside the owned cgroup."""
import argparse
import getpass
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from uuid import uuid4

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.bootstrap.paths import RuntimePaths
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment
from .supervisor import lock_workspace,service_command,service_state,unit_name,process_identity,atomic


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description='本地统一控制中心；默认允许自有仿真部署授权，页面 SEND 默认关闭。')
    parser.add_argument('--port',type=int,default=8780)
    authorization=parser.add_mutually_exclusive_group()
    authorization.add_argument('--allow-send',dest='allow_send',action='store_true',help='允许自有仿真部署授权（默认）；页面 SEND 仍默认关闭')
    authorization.add_argument('--read-only',dest='allow_send',action='store_false',help='仅观察，不允许获取仿真控制权')
    parser.set_defaults(allow_send=True)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--config',type=Path)
    parser.add_argument('--check',action='store_true',help='仅检查环境，不启动服务')
    parser.add_argument('--set-password',action='store_true',help='设置本机登录密码；运行中的控制台须先关闭')
    return parser.parse_args(argv)


def main():
    args=parse_args();root=resource_root().resolve()
    host=HostEnvironment(root)
    if host.config:os.environ['VAF_ENVIRONMENT_CONFIG']=str(host.config)
    if args.check:
        from .registry import inspect_host
        print(json.dumps(inspect_host(root,args.config),ensure_ascii=False,indent=2));return 0
    if not 1024<=args.port<=65535:raise ValueError('port must be 1024..65535')
    launcher_lock=lock_workspace(root,'launcher')
    check=subprocess.run(['systemctl','--user','show-environment'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=5)
    if check.returncode:raise RuntimeError('用户级 systemd 不可用，无法保证异常退出清理。'+check.stderr)
    unit=unit_name(root)
    if service_state(unit).get('ActiveState') in ('active','activating','deactivating'):
        raise ValueError('现有控制中心服务仍在运行或退出中；不接管、不覆盖。')
    password_file=RuntimePaths(root).slot('state', 'control-center/password.json')
    if args.set_password or not password_file.exists():
        from vehicle_autonomy.app.web.passwords import set_password
        password=getpass.getpass('设置控制台登录密码：')
        if password!=getpass.getpass('再次输入密码：'):raise ValueError('两次输入的密码不一致。')
        set_password(password_file,password)
        del password
        if args.set_password:
            print('登录密码已设置。');launcher_lock.close();return 0
    directory=RuntimePaths(root).slot('sessions', 'control-center')/('cc-'+uuid4().hex)
    directory.mkdir(mode=0o700,parents=True)
    arguments=['--port',str(args.port)]
    if args.allow_send:arguments.append('--allow-send')
    if args.config:arguments+=['--config',str(args.config.expanduser().resolve())]
    stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    started=False;ready=False
    try:
        result=subprocess.run(service_command(root,directory,arguments,os.getpid(),process_identity(os.getpid())),capture_output=True,text=True,timeout=12)
        if result.returncode:raise RuntimeError(result.stderr)
        started=True;deadline=time.monotonic()+50
        while not stopped and time.monotonic()<deadline:
            try:
                state=json.loads((directory/'state.json').read_text())
                if state['state']=='READY':ready=True;break
                if state['state']=='FAILED':raise RuntimeError(state.get('error'))
            except FileNotFoundError:pass
            if service_state(unit).get('ActiveState') not in ('active','activating'):break
            time.sleep(.2)
        if not ready and not stopped:raise RuntimeError('控制台启动未就绪；请查看 '+str(directory/'backend.log'))
        if ready:
            print('控制中心：'+state['url'],flush=True)
            print('登录方式：使用已设置的密码。',flush=True)
            print('日志目录：'+str(directory),flush=True)
            print('自有仿真部署授权：'+('允许手动控制' if state['deployment_send'] else '只读观察'),flush=True)
            print('会话：'+state['session_id']+' · 默认无场景、无工具、SEND 关闭',flush=True)
            print('Ctrl+C 或页面“关闭控制台”会关闭本次自有仿真和工具。',flush=True)
            if not args.no_browser and (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
                try:
                    opened=subprocess.run(['xdg-open',state['url']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
                    atomic(directory/'browser-open.json',dict(url=state['url'],returncode=opened.returncode,owner='launcher; browser outside managed cgroup'))
                except (OSError,subprocess.TimeoutExpired):print('浏览器未自动打开，请访问上方地址。',flush=True)
            while not stopped:
                if service_state(unit).get('ActiveState') not in ('active','activating'):break
                time.sleep(.5)
    finally:
        if started:
            subprocess.run(['systemctl','--user','stop',unit],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=135)
        launcher_lock.close()
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,RuntimeError,OSError) as exc:raise SystemExit(str(exc))
