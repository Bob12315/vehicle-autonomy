"""Owned simulation-only sensor/rosbag/RViz profiles using the existing Tool owner.

No vehicle command capability, arbitrary HTTP argv or paths, physical driver,
serial transport, SDK or radar network configuration is accepted here.
"""
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
from threading import RLock, Event, Thread, current_thread
import sys
import re
import sqlite3
import time
from types import SimpleNamespace
from uuid import uuid4

from vehicle_autonomy.app.bootstrap.paths import RuntimePaths
from vehicle_autonomy.app.control_center.registry import ros_environment, configuration, qt_environment
from vehicle_autonomy.app.control_center.supervisor import atomic
from vehicle_autonomy.app.tools.builtins import make, profile
from vehicle_autonomy.app.tools.local import LocalTools
from vehicle_autonomy.app.tools.storage import Store
from vehicle_autonomy.world.sensors.lidar.mid360_probe import health


def recover_center_recordings(manager):
    """Expose finalized bags from prior owned Center runs, never live owners.

    Center creates a new application directory at each launch. Search only its
    RuntimePaths session tree, not browser paths or historical artifacts.
    No persisted PID, ROS domain or vehicle authorization is restored.
    """
    sessions=RuntimePaths(manager.root).slot('sessions','control-center')
    for report in sorted(sessions.glob('cc-*/application/simulation/sim-*/report.json')):
        if report.resolve()!=report or report.stat().st_uid!=os.getuid():continue
        if report.is_relative_to(manager.directory):continue
        try:
            record=json.loads(report.read_text());identifier=record['id']
            if not re.fullmatch(r'sim-[0-9a-f]{32}',identifier) or report.parent.name!=identifier:continue
            if identifier in manager.records:continue
            restored={}
            for vehicle in record.get('vehicles',[]):
                vid=vehicle.get('id','')
                if not re.fullmatch(r'vehicle-[0-9a-f]{32}',vid):continue
                source=report.parent/vid/'mid360/source.json'
                if not source.is_file() or source.resolve()!=source:continue
                sensor=Mid360Tools.archive(manager.root,source,vehicle.get('target'))
                if any(b['complete'] for b in sensor.bags.values()):restored[vid]=(identifier,sensor)
            if not restored:continue
            if record['state'] not in ('FINISHED','FAILED','CANCELLED'):
                record.update(state='FAILED',cleanup='UNKNOWN',
                    error='previous backend ended; recordings only, no process or vehicle ownership restored')
            record['recordings_only']=True
            manager.records[identifier]=record
            manager.mid360_services.update(restored)
        except (OSError,ValueError,KeyError,TypeError):continue


class DomainLease:
    """Workspace-global locks across processes; retain on uncertain tool cleanup."""
    def __init__(self, root):
        directory = RuntimePaths(root).slot('state', 'mid360-domains')
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.file = None
        for domain in range(120, 200):
            path = directory/f'{domain}.lock'
            if path.is_symlink():
                raise ValueError('domain lease symlink rejected')
            handle = os.fdopen(os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600),'r+')
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                continue
            previous=handle.read()
            if previous:
                try:released=json.loads(previous).get('released') is True
                except (ValueError,AttributeError):released=False
                if not released:
                    # Crash/unknown ownership quarantines the domain. A flock
                    # alone could release before an orphan's DDS process exits.
                    handle.close()
                    continue
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(dict(released=False,pid=os.getpid(),epoch=uuid4().hex)))
            handle.flush()
            self.file, self.domain = handle, domain
            break
        if self.file is None:
            raise ValueError('simulation ROS domain budget exhausted')

    def close(self):
        if self.file:
            self.file.seek(0)
            self.file.truncate()
            self.file.write(json.dumps(dict(released=True)))
            self.file.flush()
            self.file.close()
            self.file = None


class Mid360Tools:
    def __init__(self, child, assembly, *, archive=False):
        self.child = child
        self.root, self.directory = child.owner.root, child.directory/'mid360'
        self.directory.mkdir(mode=0o700,exist_ok=archive)
        self.config = deepcopy(assembly)
        self.config_path = self.directory/'source.json'
        if not archive:self.config_path.write_text(json.dumps(self.config, indent=2)+'\n')
        self.lock = RLock()
        self.tools = None
        self.leases = {}
        self.contexts = {}
        self.bags = {}
        self.recording = None
        self.replay = None
        self.rviz_source = None
        self.live_closed = archive
        self.error = None
        self.monitor_stop = Event()
        self.monitor = None
        self.source_fault_handled = False

    @classmethod
    def archive(cls, root, source, target):
        """Restore recording metadata only; never adopt a process or live epoch."""
        source=Path(source).resolve()
        config=json.loads(source.read_text())
        if config.get('source')!='gazebo-live' or config.get('kind') not in ('rover','copter'):
            raise ValueError('invalid archived MID-360 source')
        child=SimpleNamespace(directory=source.parent.parent,id=source.parent.parent.name,target=target,
            owner=SimpleNamespace(root=Path(root),partition='retired-'+uuid4().hex))
        result=cls(child,config,archive=True)
        index=result.directory/'recordings.json'
        if index.is_file():
            saved=json.loads(index.read_text())
            for key,bag in saved.items():
                path=result.directory/'bags'/key
                if not re.fullmatch(r'bag-[0-9a-f]{32}',key) or path.resolve()!=path:
                    raise ValueError('invalid archived bag identity')
                # Reconstruct the owned path rather than trusting an absolute
                # path serialized by a previous backend.
                result.bags[key]=dict(bag,path=str(path),complete=bag.get('complete') is True and (path/'metadata.yaml').is_file())
        return result

    def _ensure(self):
        if self.tools is not None:
            return
        ros = ros_environment(self.root, configuration(self.root))
        env = dict(ros, GZ_PARTITION=self.child.owner.partition, GZ_IP='127.0.0.1',
                   ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST', ROS_LOCALHOST_ONLY='1')
        # The supervisor receives an explicit environment. Keep the real HOME
        # unchanged; route ROS logs and Qt cache into this owned tool directory.
        for key in ('HOME','USER','LANG','DISPLAY','XAUTHORITY','XDG_RUNTIME_DIR','XDG_SESSION_TYPE'):
            if os.environ.get(key):env[key]=os.environ[key]
        for key,slot in (('ROS_LOG_DIR','ros-logs'),('XDG_CACHE_HOME','cache')):
            path=self.directory/slot;path.mkdir(mode=0o700,exist_ok=True)
            env[key]=str(path)
        # Executables are resolved in the HostEnvironment ROS profile.
        self.environment = env
        manifests = [make(key, name, kind, {'default': profile(['/bin/false'])}, permissions=permissions)
            for key,name,kind,permissions in (
                ('mid360','MID-360 仿真数据桥','service',['simulation','ros_read']),
                ('record','MID-360 rosbag2 录制','service',['ros_read']),
                ('replay','MID-360 rosbag2 回放','service',['ros_read']),
                ('rviz2','MID-360 RViz2','gui',['desktop','ros_read']))]
        directory = self.directory/'tools'/uuid4().hex
        store=Store(directory)
        try:
            self.tools = LocalTools(manifests, store, environment=env,
                                    allow_external_instances=True, persist_logs=True)
        except BaseException:
            store.close()
            raise
        self.monitor_stop = Event()
        self.monitor = Thread(target=self._monitor, name='mid360-dependencies', daemon=True)
        self.monitor.start()

    def _monitor(self):
        # A lost clock publisher can freeze RViz's simulated-time decay. Close
        # the dependent viewer/recorder on worker exit, never leave an old cloud
        # displayed as if it were live. No automatic source restart or SEND.
        while not self.monitor_stop.wait(.25):
            if not self.lock.acquire(blocking=False):continue
            try:
                tools=self.tools
                if tools is None:continue
                with tools.lock:
                    source=tools.instances.get('mid360')
                    failed=source and source['process'].poll() is not None and not source['stopping']
                    replay=tools.instances.get('replay')
                    replay_failed=replay and replay['process'].poll() is not None and not replay['stopping']
                if failed and not self.source_fault_handled:
                    self.error='sensor worker exited; live dependent tools stopped'
                    self._finish_record()
                    if self.rviz_source=='live':
                        self._stop('rviz2');self.rviz_source=None
                    self.source_fault_handled=True
                if replay_failed and self.rviz_source=='replay':
                    self._stop('rviz2');self.rviz_source=None
                    self.error='replay worker exited; replay viewer stopped'
            except Exception as exc:self.error='dependency cleanup UNCONFIRMED: '+str(exc)
            finally:self.lock.release()

    def _ctx(self, source):
        if source not in self.contexts:
            lease = DomainLease(self.root)
            self.leases[source] = lease
            self.contexts[source] = dict(vehicle_id=self.child.id, vehicle_type=self.config['kind'],
                environment='simulation', ros_namespace=self.config['namespace'],
                ros_domain_id=lease.domain, mavlink_profile='no-vehicle-port')
        return self.contexts[source]

    def _launch(self, key, argv, source='live', *, ready=None, desktop=False):
        self._ensure()
        p = profile(argv, env=qt_environment(self.environment) if desktop else self.environment,
            ready=ready, health=ready, timeout=90,
            connection=dict(kind='ros2.simulation', description=source+' MID-360; visualization/recording only'))
        p['stop_timeout_s'] = 10
        with self.tools.lock:
            self.tools.registry[key]['profiles']['default'] = p
            return self.tools.execute('launch', key, 'default', self._ctx(source))

    def start(self):
        with self.lock:
            if self.live_closed:
                raise ValueError('retired simulation cannot restart its live sensor')
            if self._active('mid360'):
                with self.tools.lock:return self.tools._view(self.tools.instances['mid360'])
            # A previous process's fresh-looking status cannot qualify a new
            # process before its first actual cloud/IMU/TF publication.
            (self.directory/'health.json').unlink(missing_ok=True)
            self.error=None
            self.source_fault_handled=False
            probe = dict(argv=[sys.executable,'-m','vehicle_autonomy.world.sensors.lidar.mid360_probe',
                '--health',str(self.directory/'health.json')], contains=['"status": "READY"'], timeout_s=2)
            return self._launch('mid360', [sys.executable,'-u','-m',
                'vehicle_autonomy.world.sensors.lidar.mid360_worker','--config',str(self.config_path),
                '--output',str(self.directory)], ready=probe)

    def _stop(self, key):
        if self.tools is None:
            return
        with self.tools.lock:
            record = self.tools.instances.get(key)
            if record and record['process'].poll() is None:
                self.tools._stop(record)
        deadline = time.monotonic()+25
        while record and time.monotonic() < deadline:
            with self.tools.lock:
                if record['process'].poll() is not None and record['cleanup_confirmed']:
                    return
            time.sleep(.05)
        if record and not record['cleanup_confirmed']:
            raise RuntimeError(key+' cleanup UNCONFIRMED')

    def _active(self, key):
        tools=self.tools
        if tools is None:
            return False
        with tools.lock:
            record = tools.instances.get(key)
            return bool(record and record['process'].poll() is None and not record['stopping'])

    def _qos(self):
        path = self.directory/'bag-qos.yaml'
        ns = self.config['namespace']
        text = ''
        for topic in ('points','imu','tf','tf_static','robot_description','trajectory','status'):
            retained = topic in ('tf_static','robot_description')
            reliability = 'best_effort' if topic in ('points','imu') else 'reliable'
            text += f'{ns}/{topic}:\n  history: keep_last\n  depth: 100\n  reliability: {reliability}\n  durability: '+('transient_local' if retained else 'volatile')+'\n'
        text += '/clock:\n  history: keep_last\n  depth: 100\n  reliability: reliable\n  durability: volatile\n'
        path.write_text(text)
        return path

    def handle(self, action, *, bag_id=None, source='live'):
        if bag_id is not None and (type(bag_id) is not str or not re.fullmatch(r'bag-[0-9a-f]{32}',bag_id)):
            raise ValueError('registered recording id required')
        if source not in ('live','replay'):
            raise ValueError('source must be live or replay')
        if action not in ('status','record_start','record_stop','replay_start','replay_stop',
                          'rviz_start','rviz_stop','fault_on','fault_off','sensor_stop','sensor_start'):
            raise ValueError('unregistered MID-360 tool operation')
        with self.lock:
            if action == 'status':
                return self.snapshot()
            if action in ('record_start','fault_on','fault_off','sensor_start') and self.live_closed:
                raise ValueError('live World retired; recordings may be replayed only')
            if action == 'record_start':
                if not self.online():
                    raise ValueError('fresh live MID-360 data required for recording')
                if self._active('record'):
                    raise ValueError('recording is already running')
                if len(self.bags) >= 100:
                    raise ValueError('recording count budget exhausted')
                identity = 'bag-'+uuid4().hex
                path = self.directory/'bags'/identity
                path.parent.mkdir(mode=0o700, exist_ok=True)
                ns = self.config['namespace']
                topics = [ns+'/'+v for v in ('points','imu','tf','tf_static','robot_description','trajectory','status')]+['/clock']
                self._launch('record',['ros2','bag','record','--storage','sqlite3','--use-sim-time',
                    '--qos-profile-overrides-path',str(self._qos()),'-o',str(path),*topics])
                self.bags[identity] = dict(id=identity,path=str(path),source='gazebo-live',complete=False)
                self.recording = identity
                atomic(self.directory/'recordings.json',self.bags)
            elif action == 'record_stop':
                self._finish_record()
            elif action == 'replay_start':
                if bag_id not in self.bags or not self.bags[bag_id]['complete']:
                    raise ValueError('select a finalized owned recording id')
                self._stop('replay')
                self._ensure()
                self._launch('replay',[sys.executable,'-u','-m',
                    'vehicle_autonomy.world.sensors.lidar.mid360_replay','--config',str(self.config_path),
                    '--bag',self.bags[bag_id]['path'],'--qos',str(self._qos())], 'replay')
                self.replay = bag_id
            elif action == 'replay_stop':
                if self.rviz_source == 'replay':
                    self._stop('rviz2')
                self._stop('replay')
                self.replay = None
            elif action == 'rviz_start':
                if source == 'live' and not self.online():
                    raise ValueError('fresh live sensor required; choose replay for a recording')
                if source == 'replay' and not self._active('replay'):
                    raise ValueError('start an owned replay first')
                self._stop('rviz2')
                from vehicle_autonomy.app.control_center.desktop import diagnostic
                if not diagnostic()['available']:
                    raise ValueError('real X11/XWayland desktop unavailable; GUI readiness cannot be inferred')
                text = (self.root/'configs/rviz/mid360-visualization.rviz').read_text()
                for key,value in dict(NS=self.config['namespace'],WORLD=self.config['world_frame'],
                                      BASE=self.config['base_frame'],SOURCE=source.upper()).items():
                    text = text.replace('__'+key+'__',value)
                path = self.directory/('mid360-'+source+'.rviz')
                path.write_text(text)
                probe = dict(argv=[sys.executable,'-m','vehicle_autonomy.world.sensors.lidar.mid360_probe',
                    '--config',str(self.config_path),'--window'], contains=['"status": "READY"'], timeout_s=8)
                ns = self.config['namespace']
                self._launch('rviz2',['rviz2','-d',str(path),'--ros-args',
                    '-r','__ns:='+ns,'-r','__node:=vaf_mid360_'+source,
                    '-r','/tf:='+ns+'/tf','-r','/tf_static:='+ns+'/tf_static',
                    '-p','use_sim_time:=true'],source,ready=probe,desktop=True)
                self.rviz_source = source
            elif action == 'rviz_stop':
                self._stop('rviz2')
                self.rviz_source = None
            elif action == 'fault_on':
                (self.directory/'fault').touch()
            elif action == 'fault_off':
                (self.directory/'fault').unlink(missing_ok=True)
            elif action == 'sensor_stop':
                self._finish_record()
                if self.rviz_source == 'live':
                    self._stop('rviz2')
                self._stop('mid360')
            elif action == 'sensor_start':
                self.start()
            return self.snapshot()

    def _finish_record(self):
        self._stop('record')
        if self.recording:
            bag = self.bags[self.recording]
            path = Path(bag['path'])
            # Require real recorded messages as well as final rosbag metadata.
            counts={}
            try:
                for database in path.glob('*.db3'):
                    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as connection:
                        rows=connection.execute('SELECT topics.name,COUNT(*) FROM messages JOIN topics ON topics.id=messages.topic_id GROUP BY topics.name')
                        for topic,count in rows:counts[topic]=counts.get(topic,0)+count
            except sqlite3.Error as exc:
                bag['error']=str(exc)
            required=[self.config['namespace']+'/'+v for v in
                ('points','imu','tf','tf_static','robot_description','trajectory','status')]+['/clock']
            bag['message_counts']=counts
            bag['complete']=(path/'metadata.yaml').is_file() and all(counts.get(t,0)>0 for t in required)
            self.recording = None
            atomic(self.directory/'recordings.json',self.bags)

    def online(self):
        return not self.live_closed and self._active('mid360') and health(self.directory/'health.json')

    def snapshot(self):
        try:
            state = json.loads((self.directory/'health.json').read_text())
        except (OSError,ValueError):
            state = dict(error='awaiting sensor worker')
        if not isinstance(state,dict):state=dict(error='invalid sensor health')
        online=self.online()
        state['online']=online
        if not online and not state.get('error'):state['error']='worker stopped or sensor data stale'
        instances = {}
        tools=self.tools
        if tools:
            with tools.lock:
                instances = {k:tools._view(v) for k,v in tools.instances.items()}
        return dict(enabled=True, online=online, live_closed=self.live_closed, health=state,
            source='gazebo-live', namespace=self.config['namespace'], backend=self.config['backend'],
            domains={k:v['ros_domain_id'] for k,v in self.contexts.items()},
            rviz_source=self.rviz_source, replay_source='rosbag2' if self._active('replay') else None,
            replay=self.replay, recording=self.recording, bags=deepcopy(list(self.bags.values())),
            tools=instances, error=self.error, limitations=self.config['limitations'])

    def close(self):
        self.monitor_stop.set()
        with self.lock:
            self.live_closed = True
            self._finish_record()
            if self.tools:
                self.tools.close()  # existing supervisor verifies descendant cleanup
                self.tools.store.close()
                self.tools = None
            for lease in self.leases.values():
                lease.close()
            self.leases.clear()
            self.contexts.clear()
            self.replay = self.rviz_source = None
        if self.monitor and self.monitor is not current_thread():
            self.monitor.join(2)
            if self.monitor.is_alive():raise RuntimeError('sensor dependency monitor cleanup UNCONFIRMED')
