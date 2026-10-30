"""Read-only X11 window verification, tied to the existing ownership marker."""
import json
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def output(argv,env=None,timeout=2):
    result=subprocess.run(argv,env=env,capture_output=True,text=True,timeout=timeout)
    if result.returncode:raise ValueError((result.stderr or result.stdout)[-500:])
    return result.stdout


def diagnostic(environment=None):
    env=dict(os.environ if environment is None else environment)
    result={key:env.get(key) for key in ('DISPLAY','XAUTHORITY','WAYLAND_DISPLAY','XDG_SESSION_TYPE','XDG_RUNTIME_DIR','QT_QPA_PLATFORM')}
    result['dri_devices']=[str(p) for p in Path('/dev/dri').glob('*')]
    result['window_verification']='X11 / XWayland mapped window with owned PID'
    try:
        if not env.get('DISPLAY'):raise ValueError('没有可验证的 X11 / XWayland DISPLAY；纯 Wayland 当前不支持窗口所有权验证。')
        if env.get('QT_QPA_PLATFORM') in ('offscreen','minimal'):raise ValueError('当前 Qt 平台不创建真实窗口。')
        for exe in ('xprop','xwininfo'):
            if not shutil.which(exe):raise ValueError('缺少图形窗口检查工具：'+exe)
        output(['xwininfo','-root'],env)
        result.update(available=True,error=None)
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:result.update(available=False,error=str(exc))
    return result


def owned_processes(marker):
    if not marker:return []
    value=('VAF_TOOL_OWNERSHIP='+marker).encode();pids=[]
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():continue
        try:
            if entry.stat().st_uid==os.getuid() and value in (entry/'environ').read_bytes().split(b'\0'):pids.append(int(entry.name))
        except OSError:pass
    return pids


def windows(pids,environment=None):
    if not pids:return []
    env=dict(os.environ if environment is None else environment);result=[]
    raw=output(['xprop','-root','_NET_CLIENT_LIST'],env)
    for identifier in re.findall(r'0x[0-9a-fA-F]+',raw)[:128]:
        try:
            props=output(['xprop','-id',identifier,'_NET_WM_PID','_NET_WM_NAME','WM_NAME'],env)
            match=re.search(r'_NET_WM_PID\(CARDINAL\) = (\d+)',props)
            if not match or int(match[1]) not in pids:continue
            info=output(['xwininfo','-id',identifier],env)
            if 'Map State: IsViewable' not in info:continue
            width=re.search(r'Width: (\d+)',info);height=re.search(r'Height: (\d+)',info)
            if not width or not height or min(int(width[1]),int(height[1]))<120:continue
            title=re.search(r'(?:_NET_WM_NAME|WM_NAME)\([^)]*\) = (.+)',props)
            result.append(dict(id=identifier,pid=int(match[1]),title=title[1] if title else '',width=int(width[1]),height=int(height[1]),mapped=True))
        except (OSError,ValueError,subprocess.TimeoutExpired):pass
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--gazebo',action='store_true');parser.add_argument('--ros-config');args=parser.parse_args()
    pids=owned_processes(os.environ.get('VAF_TOOL_OWNERSHIP'))
    value=windows(pids)
    if value and args.gazebo:
        # CameraTracking publishes this pose from the render event. A visible
        # Qt shell and a Server world alone do not establish a rendered scene.
        try:
            pose=output(['gz','topic','-e','-n','1','-t','/gui/camera/pose'],timeout=2)
            if 'position {' not in pose or 'orientation {' not in pose:value=[]
        except (OSError,ValueError,subprocess.TimeoutExpired):value=[]
    if value and args.ros_config:
        try:
            ready=output([sys.executable,'-m','vehicle_autonomy.app.visualization.probe','rviz-ready','--config',args.ros_config],timeout=3.5)
            if json.loads(ready)['status']!='READY':value=[]
        except (OSError,ValueError,subprocess.TimeoutExpired):value=[]
    print(json.dumps(dict(status='READY' if value else 'WAITING',windows=value)))
    return 0 if value else 1


if __name__=='__main__':raise SystemExit(main())
