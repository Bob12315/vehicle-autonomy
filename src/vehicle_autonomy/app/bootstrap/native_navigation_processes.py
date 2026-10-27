"""Owned native Nav2 process cohort; no vehicle port or second Action runtime.

A managed external job must reserve/register itself BEFORE calling start().
All Goal servers live in this explicit cohort. Their logical Goal result alone
is not external exit proof: stop() verifies every owned process group is gone.
"""
from pathlib import Path
import json
import hashlib
import os
import re
import signal
import stat
import subprocess
import time
from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.engine.action.durable import DurableRecord
from vehicle_autonomy.engine.action.external_lifecycle import require_job_scope

NODES=(('nav2_planner','planner_server','planner'),('nav2_controller','controller_server','controller'),
       ('nav2_behaviors','behavior_server','behaviors'),('nav2_velocity_smoother','velocity_smoother','smoother'),
       ('nav2_collision_monitor','collision_monitor','collision'),('nav2_bt_navigator','bt_navigator','navigator'))


def group_exists(group):
    try:os.killpg(group,0);return True
    except ProcessLookupError:return False


class NativeNavigationProcesses:
    def __init__(self,root,namespace,security_environment):
        require_job_scope()
        self.root=Path(root).absolute()
        if self.root.resolve()!=self.root or self.root.exists():raise ValueError('fresh owned native cohort directory required')
        parent=self.root.parent;info=parent.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:raise ValueError('private registered job parent required')
        if not re.fullmatch('/nav2_[a-z0-9_]{1,40}',namespace):raise ValueError('fixed native namespace required')
        expected={'ROS_SECURITY_ENABLE','ROS_SECURITY_STRATEGY','ROS_SECURITY_KEYSTORE','RMW_IMPLEMENTATION'}
        if set(security_environment)!=expected or security_environment['ROS_SECURITY_ENABLE']!='true' or security_environment['ROS_SECURITY_STRATEGY']!='Enforce' or security_environment['RMW_IMPLEMENTATION']!='rmw_fastrtps_cpp':raise ValueError('qualified enforced DDS security required')
        self.security=dict(security_environment);self.namespace=namespace;self.entries=[];self.stopping=False;self.failed=False
        self.root.mkdir(mode=0o700);self.identity=(self.root.stat().st_dev,self.root.stat().st_ino)
        self.store=DurableRecord(self.root/'processes.json');self.store.write(dict(schema=1,phase='REGISTERED',processes=[]),create=True)
    def _save(self,phase):
        info=self.root.lstat()
        if self.root.resolve()!=self.root or (info.st_dev,info.st_ino)!=self.identity:raise ValueError('native process state directory changed')
        self.store.write(dict(schema=1,phase=phase,processes=[r for p,h,r in self.entries]))
    def _spawn(self,name,command,*,transient=False):
        require_job_scope()
        if self.stopping or self.failed:raise RuntimeError('native cohort ingress fenced')
        if len(self.entries)>=24:raise RuntimeError('native cohort process budget exhausted')
        self._save('SPAWNING:'+name)
        handle=(self.root/(name+'.log')).open('x')
        env=dict(os.environ,**self.security,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
        process=None
        try:
            process=subprocess.Popen(command,env=env,stdout=handle,stderr=subprocess.STDOUT,start_new_session=True)
            record=dict(name=name,pid=process.pid,pgid=process.pid,start_ticks=Path(f'/proc/{process.pid}/stat').read_text().rsplit(')',1)[1].split()[19],transient=transient,command=command,exit_code=None)
            self.entries.append((process,handle,record));self._save('BOOTING')
            return process
        except BaseException:
            self.failed=True
            # If spawn outcome has no registered PID, do not claim safe exit.
            if process is not None and not any(p is process for p,_,_ in self.entries):
                self.entries.append((process,handle,dict(name=name,pid=process.pid,pgid=process.pid,start_ticks=None,transient=transient,command=command,exit_code=None)))
            else:
                if process is None:handle.close()
            raise
    def start(self,*,cancelled=lambda:False):
        require_job_scope()
        if self.entries or self.failed:raise RuntimeError('cohort start is single-use')
        source=resource_root()/'simulation/phase5/nav2_rover.yaml';config=self.root/'nav2.yaml'
        config.write_text(self.namespace[1:]+':\n'+''.join('  '+line if line.strip() else line for line in source.read_text().replace('behavior_plugins: [spin, backup, wait]','behavior_plugins: [wait]').splitlines(keepends=True)))
        wrapper=str(resource_root()/'scripts/with_ros2.sh')
        for package,node,role in NODES:
            command=[wrapper,'/usr/bin/python3','-m','vehicle_autonomy.app.bootstrap.ros2_run',package,node,'--ros-args','--enclave','/vaf/'+role,'--params-file',str(config),'-r','__ns:='+self.namespace]
            if node=='bt_navigator':command+=['-p','default_nav_to_pose_bt_xml:='+str(resource_root()/'simulation/phase5/navigate_rover.xml')]
            if node in ('controller_server','behavior_server'):command+=['-r','cmd_vel:=cmd_vel_nav']
            if node=='velocity_smoother':command+=['-r','cmd_vel:=cmd_vel_nav','-r','cmd_vel_smoothed:=cmd_vel_smoothed']
            self._spawn(node,command)
        for _,node,_ in NODES:
            for transition in ('configure','activate'):
                self.assert_alive();name=node+'-'+transition
                p=self._spawn(name,[wrapper,'/usr/bin/python3','-m','vehicle_autonomy.app.bootstrap.ros2_lifecycle','--node',self.namespace+'/'+node,'--transition',transition,'--result',str(self.root/(name+'.json')),'--ros-args','--enclave','/vaf/manager'],transient=True)
                try:
                    deadline=time.monotonic()+25
                    while p.poll() is None:
                        if cancelled():raise RuntimeError('native startup cancelled')
                        if time.monotonic()>=deadline:raise TimeoutError('native lifecycle deadline')
                        time.sleep(.02)
                    code=p.returncode
                finally:self._update()
                if code:raise RuntimeError('native lifecycle result unavailable: '+name)
        self._save('READY')
    def source_receiver(self,address):
        binary=Path(os.environ.get('VAF_NATIVE_SOURCE_RECEIVER','')).absolute()
        info=binary.stat()
        if binary.resolve()!=binary or not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o022:raise ValueError('qualified owned native source adapter required')
        expected=os.environ.get('VAF_NATIVE_SOURCE_RECEIVER_SHA256')
        if not expected or hashlib.sha256(binary.read_bytes()).hexdigest()!=expected:raise ValueError('native source adapter hash not qualified')
        return self._spawn('native-source-receiver',[str(resource_root()/'scripts/with_ros2.sh'),str(binary),'--socket',address,'--namespace',self.namespace,'--ros-args','--enclave','/vaf/manager'])
    def goal_worker(self,config):
        return self._spawn('managed-goal',[str(resource_root()/'scripts/with_ros2.sh'),'/usr/bin/python3','-m','vehicle_autonomy.actions.navigation.nav2_worker','--config',str(config),'--ros-args','--enclave','/vaf/manager'],transient=True)
    def _update(self):
        for p,h,r in self.entries:
            r['exit_code']=p.poll()
            if r['exit_code'] is not None and not h.closed:h.close()
    def assert_alive(self):
        if self.failed or self.stopping or (self.root.stat().st_dev,self.root.stat().st_ino)!=self.identity:raise RuntimeError('native cohort lifetime fenced')
        self._update()
        for p,_,r in self.entries:
            if p.returncode is not None:
                if not r['transient'] or p.returncode!=0:raise RuntimeError('native process exited: '+r['name'])
            else:
                fields=Path(f'/proc/{p.pid}/stat').read_text().rsplit(')',1)[1].split()
                if fields[19]!=r['start_ticks'] or os.getpgid(p.pid)!=r['pgid']:raise RuntimeError('native process identity changed')
    def stopped_proof(self):
        if not self.stopping:return False
        try:
            self.store.read();self._update()
            return all(p.returncode is not None and not group_exists(r['pgid']) for p,_,r in self.entries)
        except (OSError,ValueError):return False
    def stop(self):
        self.stopping=True
        for sig,timeout in ((signal.SIGINT,2.),(signal.SIGTERM,2.),(signal.SIGKILL,1.)):
            for p,_,r in reversed(self.entries):
                if p.poll() is None:
                    fields=Path(f'/proc/{p.pid}/stat').read_text().rsplit(')',1)[1].split()
                    if r['start_ticks'] is None or fields[19]!=r['start_ticks'] or os.getpgid(p.pid)!=r['pgid']:continue
                    try:os.killpg(r['pgid'],sig)
                    except ProcessLookupError:pass
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline and any(p.poll() is None for p,_,_ in self.entries):time.sleep(.02)
        self._update()
        safe=all(p.returncode is not None and not group_exists(r['pgid']) for p,_,r in self.entries)
        try:self._save('STOPPED' if safe else 'UNKNOWN')
        except (OSError,ValueError):safe=False
        return safe
