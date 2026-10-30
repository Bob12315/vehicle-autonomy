"""OS-owned deployment boundary around the existing process/session owners."""
from hashlib import sha256
from vehicle_autonomy.app.bootstrap.paths import RuntimePaths
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def atomic(path, value):
    path=Path(path);temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temporary.replace(path)


def unit_name(root):
    return 'vaf-control-center-'+sha256(str(Path(root).resolve()).encode()).hexdigest()[:16]+'.service'


def lock_workspace(root, name):
    directory=RuntimePaths(root).slot('state', 'locks');directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    path=directory/('control-center.'+name+'.lock')
    descriptor=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    handle=os.fdopen(descriptor,'a+')
    try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close();raise ValueError('本工作目录的控制中心已在运行；请使用现有页面或先正常关闭。') from None
    return handle


def service_state(unit):
    result=subprocess.run(['systemctl','--user','show',unit,'--property=ActiveState,SubState,MainPID,ControlGroup,Result'],
        capture_output=True,text=True,timeout=4)
    return dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)


def service_command(root, directory, arguments, parent_pid, parent_ticks):
    # mixed allows the original owners to cancel/release in order; after main
    # exit (even SIGKILL), systemd kills ALL remaining cgroup descendants.
    def quote(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%').replace('$','$$')+'"'
    finalizer=' '.join(quote(v) for v in (sys.executable,'-m','vehicle_autonomy.app.control_center.finalize','--root',root,'--run-dir',directory))
    return ['systemd-run','--user','--unit='+unit_name(root),'--collect','--service-type=exec',
        '--property=KillMode=mixed','--property=ExitType=main','--property=TimeoutStopSec=120s',
        '--property=ExecStopPost='+finalizer,
        '--property=SendSIGKILL=yes','--property=Restart=no','--property=WorkingDirectory='+str(root),
        '--property=StandardOutput=append:'+str(directory/'backend.log'),
        '--property=StandardError=append:'+str(directory/'backend.log'),
        *['--setenv='+key+'='+value for key,value in os.environ.items() if key in (
            'DISPLAY','XAUTHORITY','WAYLAND_DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','PATH','LANG','LC_ALL',
            'VAF_ROS2_ROOT','VAF_RESOURCE_ROOT','VAF_ENVIRONMENT_CONFIG','VAF_RUNTIME_ROOT','VAF_SIM_ASSET_CACHE',
            'VAF_ARDUPILOT_ROOT','VAF_GAZEBO_PLUGIN_ROOT','VAF_FIXEDWING_ROOT','VAF_SIM_LEGACY_ASSETS')],
        sys.executable,'-m','vehicle_autonomy.app.control_center.backend',
        '--run-dir',str(directory),'--root',str(root),'--parent-pid',str(parent_pid),'--parent-ticks',str(parent_ticks),*arguments]


def process_identity(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]


def process_table(cgroup):
    # Kernel membership, never executable-name matching, authorizes ownership.
    base=Path('/sys/fs/cgroup')/cgroup.lstrip('/')
    if not cgroup or not base.is_dir():return []
    pids=set()
    for path in base.rglob('cgroup.procs'):
        try:pids.update(int(v) for v in path.read_text().split())
        except OSError:pass
    result=[]
    for pid in sorted(pids):
        try:
            fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
            cmd=Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')[:700]
            result.append(dict(pid=pid,ppid=int(fields[1]),state=fields[0],start_ticks=fields[19],
                command=cmd,rss_bytes=int(fields[21])*os.sysconf('SC_PAGE_SIZE'),
                cpu_seconds=(int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK')))
        except (OSError,ValueError,IndexError):pass
    return result


class Resources:
    def __init__(self):self.previous=None
    def sample(self, processes):
        now=time.monotonic();cpu=sum(p['cpu_seconds'] for p in processes);percent=None
        if self.previous:
            elapsed=now-self.previous[0]
            percent=max(0,(cpu-self.previous[1])/elapsed*100) if elapsed else None
        self.previous=(now,cpu)
        return dict(cpu_percent=percent,rss_mib=sum(p['rss_bytes'] for p in processes)/1048576,
            process_count=len(processes),scope='owned cgroup processes; summed RSS may include shared pages')
