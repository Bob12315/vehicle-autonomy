"""Local UI use cases composing existing LocalTools and SimulationManager."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from threading import Event,RLock,Thread
import time
from uuid import uuid4

from vehicle_autonomy.app.tools.local import LocalTools
from vehicle_autonomy.app.tools.schema import context,object_fields,manifest
from vehicle_autonomy.app.tools.storage import Store
from vehicle_autonomy.app.visualization.rviz import render
from .desktop import diagnostic,owned_processes,windows
from .registry import definitions,inspect_host
from .supervisor import atomic,process_table,Resources


class ControlCenter:
    def __init__(self,application,root,directory,session_id,source_config,stop,cgroup,config=None):
        self.application=application;self.root=Path(root);self.directory=Path(directory);self.session_id=session_id
        self.stop=stop;self.cgroup=cgroup;self.source_config=Path(source_config)
        self.host=inspect_host(root,config);self.resources=Resources();self.lock=RLock();self.closed=Event()
        self.operation=None;self.worker=None;self.bindings={};self.error=None
        self.store=Store(self.directory/'tools')
        self.tools=LocalTools(definitions(self.host,self.source_config),self.store,allow_external_instances=True,persist_logs=True)
        self.application.simulation_manager.runtime_options['qgc_monitor_port']=self.host['config']['qgc_port']
        self.monitor=Thread(target=self._monitor,name='center-bindings',daemon=True);self.monitor.start()
        self._save_registry()

    def _save_registry(self):
        atomic(self.directory/'tool-registry.json',dict(schema=1,session_id=self.session_id,
            desktop=self.host['desktop'],ros_error=self.host['ros_error'],tools=list(self.tools.registry.values()),
            cwd_policy='private tool instance directory; selected World resources supplied by its owner',
            log_directory=str(self.store.root/'logs'),instances={k:{field:r.get(field) for field in ('instance_id','pid','cwd','log_path','state')} for k,r in self.tools.instances.items()}))

    def _world(self,identifier):
        manager=self.application.simulation_manager
        if identifier is None:
            records=[r for r in manager.handle('simulation.sessions',{}) if r['state'] in ('READY','RUNNING')]
            if len(records)!=1:raise ValueError('请选择一个正在运行的仿真 World。')
            identifier=records[0]['id']
        record=manager.sample(identifier)
        if record['state'] not in ('READY','RUNNING') or record.get('operation',{}).get('state')=='RUNNING':raise ValueError('仿真 World 尚未就绪或正在更换车辆。')
        owner=manager.owners.get(identifier)
        if owner is None or owner.session is None:raise ValueError('当前后台不拥有该 World。')
        return record,owner

    def _context(self,target):
        if target:
            driver=self.application.drivers.get(target)
            if driver is None or not driver.info().get('connected'):raise ValueError('请选择当前已连接的车辆。')
            kind=driver.context().target_kind
        else:kind='rover';target='empty-viewer'
        return context(dict(vehicle_id=target,vehicle_type=kind,environment='simulation',
            ros_namespace='/'+target.replace('-','_'),ros_domain_id=91,mavlink_profile='monitor'))

    def _profile(self,tool_id,world_id,target):
        p=self.tools.registry[tool_id]['profiles']['default'];ctx=self._context(target if tool_id=='rviz2' else None)
        binding={}
        if tool_id=='gazebo-gui':
            record,owner=self._world(world_id)
            # Use exactly this Server's transport partition and owned model paths.
            p['env']=dict(owner.session.env,QT_QPA_PLATFORM='xcb')
            # Full inherited environment may include unrelated secrets and exceeds
            # manifest budgets. Only simulator/desktop inputs cross the profile.
            p['env']={k:v for k,v in p['env'].items() if k.startswith('GZ_') or k in ('QT_QPA_PLATFORM','DISPLAY','XAUTHORITY','WAYLAND_DISPLAY','XDG_RUNTIME_DIR')}
            binding=dict(world_id=record['id'],partition=owner.partition,world=owner.world)
        elif tool_id=='rviz2':
            if self.host['ros_error']:raise ValueError('ROS 2 环境不可用：'+self.host['ros_error'])
            config=json.loads(self.source_config.read_text());text,names=render(ctx,config)
            directory=self.directory/'rviz-profiles'/ctx['vehicle_id'];directory.mkdir(mode=0o700,parents=True,exist_ok=True)
            path=directory/(ctx['vehicle_type']+'.rviz');path.write_text(text)
            p['argv']=[self.host['tools']['rviz2']['executable'] or '/NOT_FOUND/rviz2','-d',str(path),
                *self.host['config']['tools']['rviz2']['args'],'--ros-args','-r','__ns:='+names['namespace'],
                '-r','__node:=vaf_rviz','-r','/tf:='+names['tf'],'-r','/tf_static:='+names['tf_static'],
                '-r','/goal_pose:='+names['topic']+'/pending_goal']
            p['ready']=deepcopy(p['health'])
            if target:p['ready']['argv']+=['--ros-config',str(self.source_config)]
            binding=dict(target=target,missing_topics=['PointCloud','Map','external Path'],note='仅显示真实 Framework TF、Odometry 和实际轨迹；未接入的点云、地图关闭。' if target else '未选择车辆：空白显示 Profile；缺少实时 TF、Odometry、点云、地图。')
        elif tool_id=='qgroundcontrol':
            # Persistent project-private Qt config; never touch ~/.config/QGroundControl.
            private=self.root/'runtime/control-center/qgc';private.mkdir(mode=0o700,parents=True,exist_ok=True)
            for name in ('config','cache','data'): (private/name).mkdir(mode=0o700,exist_ok=True)
            p['env'].update(XDG_CONFIG_HOME=str(private/'config'),XDG_CACHE_HOME=str(private/'cache'),XDG_DATA_HOME=str(private/'data'))
            for organization in ('QGroundControl','QGroundControl.org'):
                destination=private/'config'/organization/'QGroundControl.ini';destination.parent.mkdir(mode=0o700,exist_ok=True)
                self._qgc_config(destination)
            binding=dict(endpoint='127.0.0.1:'+str(self.host['config']['qgc_port']),telemetry_only=True,
                note='窗口就绪不代表收到飞控；真实连接以 QGC 飞控界面为准。',config_directory=str(private))
        # Validate after trusted dynamic binding; HTTP never supplies argv/env.
        manifest(self.tools.registry[tool_id]);self._save_registry()
        return ctx,binding

    def _qgc_config(self,path):
        import configparser
        parser=configparser.ConfigParser();parser.optionxform=str
        if path.exists():parser.read(path)
        for section in ('AutoConnect','LinkManager'):
            if not parser.has_section(section):parser.add_section(section)
            for key in ('Pixhawk','SiKRadio','LibrePilot','ZeroConf','RTK','NmeaPort'):parser.set(section,'autoConnect'+key,'false')
            parser.set(section,'autoConnectUDP','true');parser.set(section,'udpListenPort',str(self.host['config']['qgc_port']))
            parser.set(section,'udpTargetHostIP','127.0.0.1');parser.set(section,'udpTargetHostPort',str(self.host['config']['qgc_port']))
        if not parser.has_section('General'):parser.add_section('General')
        parser.set('General','SettingsVersion','9');parser.set('General','firstRunPromptIdsShown','3')
        parser.set('General','savePath',str(self.root/'runtime/control-center/qgc/data'))
        temporary=path.with_suffix('.tmp')
        with temporary.open('w') as output:parser.write(output,space_around_delimiters=False)
        temporary.replace(path)

    def _wait_stop(self,tool_id):
        with self.tools.lock:
            record=self.tools.instances.get(tool_id)
            if record and record['process'].poll() is None:self.tools._stop(record)
        deadline=time.monotonic()+28
        while record and time.monotonic()<deadline:
            with self.tools.lock:
                if record['process'].poll() is not None and record['cleanup_confirmed']:return
            time.sleep(.05)
        if record and not record['cleanup_confirmed']:raise RuntimeError('工具进程清理未确认；拒绝重新启动。')

    def _perform(self,payload):
        tool_id=payload.get('tool_id');action=payload['action']
        if action=='stop_all':
            for key in ('rviz2','visualization-bridge','qgroundcontrol','gazebo-gui'):self._wait_stop(key)
            return
        if action in ('stop','restart'):
            self._wait_stop(tool_id)
            if tool_id=='rviz2':self._wait_stop('visualization-bridge')
            if action=='stop':return
        with self.tools.lock:
            current=self.tools.instances.get(tool_id)
            if current and current['process'].poll() is None:
                requested={k:payload[k] for k in ('world_id','target') if payload.get(k)}
                if any(self.bindings.get(tool_id,{}).get(k)!=v for k,v in requested.items()):raise ValueError('运行中的工具属于另一 World 或车辆；请先关闭。')
                return
            if not diagnostic()['available']:raise ValueError('真实图形会话不可用：'+str(diagnostic()['error']))
            ctx,binding=self._profile(tool_id,payload.get('world_id'),payload.get('target'))
        if tool_id=='rviz2' and payload.get('target'):
            self._wait_stop('visualization-bridge')
            self.tools.execute('launch','visualization-bridge','default',ctx)
        self.tools.execute('launch',tool_id,'default',ctx)
        self.bindings[tool_id]=binding
        self._save_registry()

    def handle(self,operation,payload):
        if operation=='center.state':return self.snapshot()
        if operation=='center.logs':
            object_fields(payload,('tool_id',))
            if payload['tool_id'] not in self.tools.registry:raise ValueError('未注册的工具。')
            with self.tools.lock:record=self.tools.instances.get(payload['tool_id']);path=record.get('log_path') if record else None
            if not path or not Path(path).exists():return dict(text='暂无日志。',path=path)
            with Path(path).open('rb') as source:source.seek(max(0,Path(path).stat().st_size-32768));text=source.read(32768).decode(errors='replace')
            return dict(text=text,path=path)
        if operation=='center.shutdown':
            object_fields(payload,('session_id',));self._epoch(payload)
            self.store.audit('center.shutdown',session_id=self.session_id)
            self.stop.set();return dict(state='STOPPING',session_id=self.session_id)
        if operation!='center.tool':raise ValueError('未注册的控制台操作。')
        object_fields(payload,('session_id','action'),('tool_id','world_id','target'));self._epoch(payload)
        if payload['action'] not in ('start','stop','restart','stop_all'):raise ValueError('工具操作不在白名单。')
        if payload['action']!='stop_all' and payload.get('tool_id') not in ('gazebo-gui','rviz2','qgroundcontrol'):raise ValueError('工具不在白名单。')
        for key in ('world_id','target'):
            if key in payload and payload[key] is not None and (not isinstance(payload[key],str) or len(payload[key])>100):raise ValueError('无效的工具绑定。')
        with self.lock:
            if self.closed.is_set() or self.stop.is_set():raise ValueError('控制中心正在退出。')
            if self.worker and self.worker.is_alive():raise ValueError('工具操作正在进行，请等待状态更新。')
            self.operation=dict(id=uuid4().hex,state='RUNNING',request=deepcopy(payload),error=None)
            def run():
                try:self._perform(payload);state='SUCCEEDED';error=None
                except Exception as exc:state='FAILED';error=str(exc)
                with self.lock:self.operation.update(state=state,error=error)
                self.store.audit('center.tool.result',state=state,error=error)
            self.worker=Thread(target=run,name='center-tool-operation',daemon=True);self.worker.start()
            return deepcopy(self.operation)

    def _epoch(self,payload):
        if payload['session_id']!=self.session_id:raise ValueError('控制中心会话已更换，请刷新页面。')

    def _monitor(self):
        while not self.closed.wait(.6):
            if self.stop.is_set():continue
            try:
                for key,binding in tuple(self.bindings.items()):
                    if key=='gazebo-gui' and binding.get('world_id'):
                        manager=self.application.simulation_manager
                        record=manager.sample(binding['world_id'])
                        if record['state'] not in ('READY','RUNNING'):self._wait_stop(key)
                    if key=='rviz2' and binding.get('target'):
                        driver=self.application.drivers.get(binding['target'])
                        if not driver or not driver.info().get('connected'):
                            self._wait_stop(key);self._wait_stop('visualization-bridge')
                    if key=='rviz2':
                        with self.tools.lock:record=self.tools.instances.get(key)
                        if record and record['process'].poll() is not None:self._wait_stop('visualization-bridge')
            except Exception as exc:self.error=str(exc)

    def snapshot(self):
        tools=self.tools.snapshot();result=[]
        with self.tools.lock:markers={k:r['ownership_marker'] for k,r in self.tools.instances.items()}
        for value in tools:
            key=value['manifest']['id']
            if key=='visualization-bridge':continue
            record=value['instance'];value['binding']=deepcopy(self.bindings.get(key,{}))
            value['executable']=self.host['tools'][key]['executable'];value['desktop']=self.host['desktop']
            if record:
                pids=owned_processes(markers.get(key));record['pids']=pids
                try:record['windows']=windows(pids) if pids else []
                except Exception:record['windows']=[]
                record['uptime_s']=max(0,time.time()-record['started_at']) if record['process_running'] else 0
                # A pid/ROS node alone never means the native GUI is ready.
                if not record['windows']:record['ready']=False
            result.append(value)
        processes=process_table(self.cgroup)
        with self.lock:operation=deepcopy(self.operation)
        return dict(session_id=self.session_id,state='STOPPING' if self.stop.is_set() else 'READY',pid=os.getpid(),
            cgroup=self.cgroup,tools=result,operation=operation,processes=processes,resources=self.resources.sample(processes),
            desktop=self.host['desktop'],ros_error=self.host['ros_error'],error=self.error,
            log_directory=str(self.directory),registry_path=str(self.directory/'tool-registry.json'))

    def summary(self):
        """Cheap projection for existing control pages; no OS/ROS probes here."""
        with self.tools.lock:
            record=self.tools.instances.get('rviz2')
            ready=bool(record and record['ready'])
            state='STOPPED' if record is None else record['state']
        with self.lock:operation=deepcopy(self.operation)
        return dict(session_id=self.session_id,rviz2_available=bool(self.host['tools']['rviz2']['installed']
            and not self.host['ros_error'] and self.host['desktop']['available'] and not self.stop.is_set()),
            rviz2_state=state,rviz2_ready=ready,operation=operation)

    def close(self):
        self.closed.set();self.monitor.join(30)
        if self.worker:self.worker.join(35)
        try:self.tools.close()
        finally:self.store.close()
