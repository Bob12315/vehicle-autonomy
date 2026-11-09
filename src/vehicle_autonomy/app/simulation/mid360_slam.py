"""Simulation LIO tools and persistent map management, shared by both vehicles."""
from datetime import datetime,timezone
import hashlib,json,sys,time
import math
from uuid import uuid4
from pathlib import Path

from vehicle_autonomy.app.bootstrap.paths import RuntimePaths
from vehicle_autonomy.app.tools.builtins import make,profile
from vehicle_autonomy.contracts.streams import DataReference
from vehicle_autonomy.world.localization.lio_input import LioWorldSource
from vehicle_autonomy.world.mapping.cloud_maps import MapCatalog,load_limits
from vehicle_autonomy.world.mapping.fast_lio_config import configure
from vehicle_autonomy.world.sensors.stream_store import StreamReader


class Mid360Slam:
    """Lock order is parent MID-360 lock then LocalTools lock, no vehicle writer."""
    def __init__(self,parent):
        self.parent=parent;self.directory=None;self.config=None;self.world=None;self.source=None;self.error=None;self.loaded=None
        self.catalog=MapCatalog(RuntimePaths(parent.root).slot('state','maps3d'))
        self.started_at=None
        self.unavailable_since=None
        self.relocation_unavailable_since=None
        self.relocation=None;self.relocation_world=None
        self.rviz_mode=None
        self.pgo_directory=None;self.pgo_error=None
        self.viewer_error=None
        self.viewer_events=[]

    def start(self,source='live'):
        p=self.parent
        with p.lock:
            if source not in ('live','replay'):raise ValueError('explicit live/replay SLAM source required')
            if p.config['backend']!='livox-gz-sliced-pattern-v1':raise ValueError('enable MID-360 timed LIO sensor and restart World')
            if source=='live' and not p.online():raise ValueError('fresh owned live sensor required')
            if source=='replay' and not p._active('replay'):raise ValueError('owned replay required')
            limits=load_limits(p.root)
            self.stop();p._ensure()
            for key,name in (('fast-lio','FAST-LIO2'),('lio-adapter','LIO 只读定位与地图'),('slam-rviz','SLAM RViz2')):
                with p.tools.lock:
                    p.tools.registry[key]=make(key,name,'gui' if key=='slam-rviz' else 'service',
                        {'default':profile(['/bin/false'])},permissions=['simulation','ros_read'])
            generation=uuid4().hex;directory=p.directory/'slam'/generation;directory.mkdir(mode=0o700,parents=True)
            base='lio_'+generation
            frames={key:base+'/'+key for key in ('map','odom','base','lidar')}
            cfg=dict(schema=1,generation=generation,created_at=datetime.now(timezone.utc).isoformat(),source=source,sensor=p.config,frames=frames,
                map_limits=limits)
            cfgpath=directory/'config.json';cfgpath.write_text(json.dumps(cfg,indent=2)+'\n')
            params,args,_=configure(p.root,p.config,directory)
            self.directory,self.config,self.source=directory,cfg,source;self.error=None
            self.unavailable_since=None;self.relocation_unavailable_since=None;self.pgo_directory=None;self.pgo_error=None
            self.relocation=None;self.relocation_world=None;self.loaded=None;self.rviz_mode=None
            self.viewer_events=[]
            self.started_at=time.monotonic()
            self.world=LioWorldSource(directory,generation,frames['map'])
            try:
                p._launch('lio-adapter',[sys.executable,'-u','-m','vehicle_autonomy.world.mapping.lio_worker',
                    '--config',str(cfgpath),'--output',str(directory)],source)
                p._launch('fast-lio',[sys.executable,'-u','-m','vehicle_autonomy.app.simulation.fast_lio_process',
                    '--params',str(params),*args],source)
            except BaseException:self.stop();raise
            return self.snapshot()

    def stop(self):
        p=self.parent
        with p.lock:
            for key in ('slam-rviz','slam-observer','map-view','relocated-map','relocalization','sc-pgo','fast-lio','lio-adapter'):p._stop(key)
            if self.world:self.world.update(owner_running=False)
            if self.relocation_world:self.relocation_world.update(owner_running=False)
            self.started_at=None

    def supervise(self):
        """Called by the existing sensor owner monitor, including fault cleanup."""
        if self.started_at is None:return
        p=self.parent
        status=self.snapshot()
        if not status['running'] or self.world.latched or self.world.raw and self.world.raw.get('fault_latched'):
            self.error=status['error'] or 'LIO worker failure';self.stop()
            return
        if status['online']:self.unavailable_since=None
        elif self.world.raw and self.world.raw.get('revision',0)>0:
            if self.unavailable_since is None:self.unavailable_since=time.monotonic()
            # Window creation can briefly contend with render/ROS startup.
            # World state is already withdrawn and the independent received-
            # data probe reports WAITING. Do not destroy a healthy user's
            # window for a recoverable short gap. Clock loss can freeze RViz
            # time, so it still closes immediately; latched/process faults
            # already take the unconditional stop path above.
            close_view='clock' in str(status['error']).lower() or time.monotonic()-self.unavailable_since>=1.
            if close_view and self.rviz_mode=='lio' and p._active('slam-rviz'):
                self.viewer_error=dict(reason='LIO source unavailable',detail=status['error'],
                    source_error=status['state'].get('error'),at_host_ns=time.monotonic_ns())
                self.viewer_events=(self.viewer_events+[self.viewer_error])[-10:]
                p._stop('slam-rviz')
            if time.monotonic()-self.unavailable_since>5:
                self.error=status['error'] or 'LIO remained unavailable';self.stop();return
        relocated_ready=status['relocalization'].get('online') and status['state'].get('relocation_tf',{}).get('online')
        if relocated_ready:self.relocation_unavailable_since=None
        elif self.rviz_mode=='relocated':
            now=time.monotonic()
            if self.relocation_unavailable_since is None:self.relocation_unavailable_since=now
            # The capture-time TF and read-only pose have already been
            # withdrawn. Keep only the window during a brief render startup
            # gap, as for local LIO; never refresh an old match or TF stamp.
            clock_fault='clock' in str(status['error']).lower()
            if (clock_fault or now-self.relocation_unavailable_since>=1.) and p._active('slam-rviz'):
                self.viewer_error=dict(reason='saved-map localization/TF unavailable',localization=status['relocalization'].get('error'),
                    transform=status['state'].get('relocation_tf'),at_host_ns=time.monotonic_ns())
                self.viewer_events=(self.viewer_events+[self.viewer_error])[-10:]
                p._stop('slam-rviz')
        # Fail closed on explicit resource exhaustion. No silent truncation of
        # a supposedly complete global map or uncontrolled keyframe growth.
        with p.tools.lock:
            for key,limit in (('fast-lio',2048),('lio-adapter',1024),('sc-pgo',2048)):
                record=p.tools.instances.get(key)
                if not record or record['process'].poll() is not None:continue
                try:
                    text=Path('/proc',str(record['pid']),'status').read_text()
                    rss=int(next(line.split()[1] for line in text.splitlines() if line.startswith('VmRSS:')))/1024
                except (OSError,StopIteration,ValueError):continue
                if rss>limit:self.error=key+' memory budget exceeded';self.stop();return
            mapper=status['state'].get('map_worker',{}).get('pid')
            adapter=p.tools.instances.get('lio-adapter')
            if type(mapper) is int and adapter:
                try:
                    proc=Path('/proc',str(mapper));stat=proc.joinpath('stat').read_text().split(') ',1)[1].split()
                    if int(stat[1])!=adapter['pid']:raise ValueError('map child ownership changed')
                    text=proc.joinpath('status').read_text()
                    rss=int(next(line.split()[1] for line in text.splitlines() if line.startswith('VmRSS:')))/1024
                    if rss>1024:self.error='map process memory budget exceeded';self.stop();return
                except (OSError,StopIteration,ValueError):pass  # Adapter reports child death/resource withdrawal.
        if self.pgo_directory:
            if len(list((self.pgo_directory/'Scans').glob('*.pcd')))>1000:
                p._stop('sc-pgo');self.pgo_error='keyframe capacity exhausted; local LIO continues'
            elif not p._active('sc-pgo'):self.pgo_error=self.pgo_error or 'loop worker stopped; no valid global correction'

    def start_pgo(self):
        if not self.snapshot()['online']:raise ValueError('fresh LIO required')
        from vehicle_autonomy.app.bootstrap.mid360_slam_environment import checked
        p=self.parent;_,binary,_=checked(p.root,'pgo');p._stop('sc-pgo');self._register('sc-pgo','Scan Context 回环与位姿图')
        folder=self.directory/('pgo-'+uuid4().hex);folder.mkdir(mode=0o700)
        self.pgo_directory=folder;self.pgo_error=None
        (self.directory/'pgo-epoch').write_text(folder.name)
        prefix=p.config['namespace']+'/slam';args=[str(binary),'--ros-args','-r','__node:=vaf_sc_pgo','-r','__ns:='+prefix+'/pgo',
            '-p','use_sim_time:=true','-p','publish_tf:=false','-p','use_current_stamp_for_aft_pgo_odom:=false',
            '-p','save_directory:='+str(folder)+'/', '-p','keyframe_meter_gap:=0.1','-p','keyframe_deg_gap:=10.0',
            '-p','sc_max_radius:=20.0','-p','sc_dist_thres:=0.2','-p','mapviz_filter_size:=0.15']
        remaps={'/velodyne_cloud_registered_local':'body_raw','/aft_mapped_to_init':'odometry_raw','/gps/fix':'pgo/unused_gps',
            '/aft_pgo_odom':'pgo/odometry','/aft_pgo_path':'pgo/trajectory','/aft_pgo_map':'pgo/map',
            '/repub_odom':'pgo/repub_odom','/loop_scan_local':'pgo/loop_scan','/loop_submap_local':'pgo/loop_submap',
            '/vaf_pgo_status':'pgo/status','/tf':'pgo/unused_tf','/tf_static':'pgo/unused_tf_static'}
        for a,b in remaps.items():args+=['-r',a+':='+prefix+'/'+b]
        return p._launch('sc-pgo',args,self.source)

    def relocalize(self,identity,seed):
        with self.parent.lock:return self._relocalize(identity,seed)

    def _relocalize(self,identity,seed):
        if not self.snapshot()['online']:raise ValueError('fresh LIO and an explicit saved map required')
        if type(seed) is not list or len(seed)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in seed):raise ValueError('rough map-to-LIO seed [x,y,z,yaw] required')
        if max(abs(v) for v in seed[:3])>80 or abs(seed[3])>3.1416:raise ValueError('rough map seed outside simulation map bounds')
        from vehicle_autonomy.app.bootstrap.mid360_slam_environment import checked
        p=self.parent;base,module,manifest=checked(p.root,'relocalization');metadata,data=self.catalog.load(identity)
        if metadata['frame_epoch']==self.config['generation']:raise ValueError('select a map from a different SLAM session')
        if self.relocation and self.relocation['map_id']!=identity:raise ValueError('restart SLAM before selecting a different saved map frame')
        if metadata['sensor']['backend']!=p.config['backend'] or metadata['world']['scene']!=p.config.get('scene_id'):
            raise ValueError('saved map sensor/world provenance mismatch')
        p._stop('relocalization');self._register('relocalization','已有地图 ICP 重定位')
        generation=uuid4().hex;directory=self.directory/'relocation'/generation;directory.mkdir(parents=True,mode=0o700)
        (directory/'map.pcd').write_bytes(data)
        cfg=dict(map=metadata,generation=generation,sensor=p.config,source=self.source,seed=seed,local_odom_frame=self.config['frames']['odom'],
            algorithm_module=dict(path=str(module),sha256=manifest['builds']['relocalization']['sha256']))
        path=directory/'config.json';path.write_text(json.dumps(cfg,indent=2)+'\n')
        from vehicle_autonomy.app.control_center.supervisor import atomic
        atomic(self.directory/'relocation-source.json',dict(generation=generation,frame_id=metadata['frame_id'],map_id=identity))
        self.relocation=dict(directory=directory,map_id=identity)
        self.relocation_world=LioWorldSource(directory,generation,metadata['frame_id'],max_age_ns=750_000_000,producer='fast-lio-localization2')
        return p._launch('relocalization',[str(base/'build-venv/bin/python'),'-u','-m',
            'vehicle_autonomy.world.mapping.relocalization_worker','--config',str(path)],self.source)

    def snapshot(self):
        p=self.parent
        with p.lock:
            running=p._active('fast-lio') and p._active('lio-adapter')
            if self.world:self.world.update(owner_running=running)
            raw=self.world.raw if self.world and self.world.raw else {}
            online=running and self.world.error is None if self.world else False
            pgo=raw.get('pgo',{});pgo_fresh=0<=time.monotonic_ns()-pgo.get('received_host_ns',0)<1_000_000_000
            global_state=('已应用 '+str(pgo['applied_loop_constraints'])+' 条回环约束（历史地图）'
                if pgo_fresh and pgo.get('applied_loop_constraints',0)>0 else '等待有效回环；未声明全局一致性')
            relocation=None
            if self.relocation_world:
                self.relocation_world.update(owner_running=p._active('relocalization') and online)
                relocation=dict(online=self.relocation_world.error is None,error=self.relocation_world.error,state=self.relocation_world.raw)
            return dict(enabled=p.config['backend']=='livox-gz-sliced-pattern-v1',running=running,online=online,
                source=self.source,error=self.error or (self.world.error if self.world else 'SLAM not started'),
                generation=self.config['generation'] if self.config else None,state=raw,
                viewer_error=self.viewer_error,
                viewer_events=list(self.viewer_events),
                localization_contract='LocalizationEstimate → read-only WorldSnapshot',
                control_source='ArduPilot reported state; LIO is read-only',
                global_consistency=self.pgo_error or (global_state if p._active('sc-pgo') else '回环模块未运行'),
                relocalization=relocation or dict(online=False,error='not started; PCD display does not recover localization'))

    def _register(self,key,name,kind='service'):
        p=self.parent;p._ensure()
        with p.tools.lock:p.tools.registry[key]=make(key,name,kind,{'default':profile(['/bin/false'])},permissions=['simulation','ros_read'])

    def load(self,identity):
        p=self.parent;metadata,data=self.catalog.load(identity)
        p._stop('slam-rviz');p._stop('slam-observer');p._stop('map-view');self._register('map-view','已保存地图查看')
        directory=p.directory/'map-views'/uuid4().hex;directory.mkdir(mode=0o700,parents=True)
        (directory/'map.pcd').write_bytes(data)
        cfg=dict(namespace=p.config['namespace']+'/saved',frame_id=metadata['frame_id'],sha256=metadata['sha256'])
        path=directory/'view.json';path.write_text(json.dumps(cfg))
        p._launch('map-view',[sys.executable,'-u','-m','vehicle_autonomy.world.mapping.saved_cloud_worker','--config',str(path)],'map')
        self.loaded=dict(metadata=metadata,config=str(path))
        return dict(map=metadata,status='loaded for display only; no localization recovered')

    def rviz(self,loaded=False,relocated=False):
        with self.parent.lock:return self._rviz(loaded,relocated)

    def _rviz(self,loaded=False,relocated=False):
        p=self.parent
        if loaded:
            if not self.loaded or not p._active('map-view'):raise ValueError('load a saved map first')
            config_path=self.loaded['config'];cfg=json.loads(Path(config_path).read_text());source='map'
            text=(p.root/'configs/rviz/mid360-loaded-map.rviz').read_text()
            bindings=dict(NS=cfg['namespace'],WORLD=cfg['frame_id'])
        else:
            if not self.snapshot()['online']:raise ValueError('fresh LIO output required')
            config_path=str(self.directory/'config.json');source=self.source
            text=(p.root/'configs/rviz/mid360-slam.rviz').read_text()
            bindings=dict(NS=p.config['namespace']+'/slam',WORLD=self.config['frames']['map'],BASE=self.config['frames']['base'],SOURCE=source.upper(),
                PGO_ENABLED='true' if p._active('sc-pgo') else 'false',RELOCATED_ENABLED='true' if relocated else 'false')
            if relocated:
                if not self.snapshot()['relocalization']['online']:raise ValueError('fresh qualified saved-map localization required')
                if not self.snapshot()['state'].get('relocation_tf',{}).get('online'):raise ValueError('waiting for capture-time saved-map TF admission')
                cfg=json.loads((self.relocation['directory']/'config.json').read_text());metadata=cfg['map']
                p._stop('relocated-map');self._register('relocated-map','已重定位地图叠加')
                view_cfg=self.relocation['directory']/'view.json'
                view_cfg.write_text(json.dumps(dict(namespace=p.config['namespace']+'/slam',frame_id=metadata['frame_id'],
                    sha256=metadata['sha256'],anchor_enabled=False)))
                p._launch('relocated-map',[sys.executable,'-u','-m','vehicle_autonomy.world.mapping.saved_cloud_worker',
                    '--config',str(view_cfg)],self.source)
                probe_config=dict(self.config,frames=dict(self.config['frames'],map=metadata['frame_id']),registered_channel='relocated_registered')
                config_path=str(self.directory/'relocated-probe.json');Path(config_path).write_text(json.dumps(probe_config))
                bindings['WORLD']=metadata['frame_id'];bindings['SOURCE']='RELOCALIZED '+source.upper()
                # Historical local-gauge PGO clouds predate saved-map match
                # TF. Keep them in the separate local view, never transform
                # their old stamps with a newly obtained alignment.
                bindings['PGO_ENABLED']='false'
                text=text.replace('Value: __NS__/registered\n','Value: __NS__/relocated_registered\n')
                text=text.replace('Name: Estimated bounded LIO trajectory\n    Enabled: true','Name: Estimated bounded LIO trajectory\n    Enabled: false')
                text=text.replace('Name: Accumulated estimated voxel map\n    Enabled: true','Name: Accumulated estimated voxel map\n    Enabled: false')
                text=text.replace('Name: Local LIO map (not globally aligned)','Name: Saved map frame matched by ICP (read-only)')
        from vehicle_autonomy.app.control_center.desktop import diagnostic
        if not diagnostic()['available']:raise ValueError('real desktop unavailable')
        for key,value in bindings.items():text=text.replace('__'+key+'__',value)
        p._stop('slam-rviz');p._stop('slam-observer');self._register('slam-rviz','SLAM RViz2','gui')
        directory=self.directory or p.directory;path=directory/'slam-view.rviz';path.write_text(text)
        health=directory/('view-health-'+uuid4().hex+'.json');self._register('slam-observer','SLAM 画面数据观察')
        p._launch('slam-observer',[sys.executable,'-u','-m','vehicle_autonomy.app.simulation.lio_probe',
            '--config',config_path,'--output',str(health)],source)
        probe=dict(argv=[sys.executable,'-m','vehicle_autonomy.app.simulation.lio_probe','--health',str(health),'--window'],contains=['"status": "READY"'],timeout_s=3)
        prefix=bindings['NS']
        self.rviz_mode='loaded' if loaded else 'relocated' if relocated else 'lio'
        self.viewer_error=None
        return p._launch('slam-rviz',['rviz2','-d',str(path),'--ros-args','-r','__node:=vaf_slam_view',
            '-r','__ns:='+prefix,'-r','/tf:='+prefix+'/tf','-r','/tf_static:='+prefix+'/tf_static',
            '-p','use_sim_time:='+('false' if loaded else 'true')],source,ready=probe,desktop=True)

    def handle(self,payload):
        action=payload['action']
        with self.parent.lock:
            if action=='start':self.start(payload.get('source','live'))
            elif action=='pgo_start':return self.start_pgo()
            elif action=='relocalize':return self.relocalize(payload.get('map_id'),payload.get('seed'))
            elif action=='stop':self.stop()
            elif action=='pause':return self.pause(True)
            elif action=='resume':return self.pause(False)
            elif action in ('tf_fault_on','tf_fault_off'):
                if not self.directory or not self.parent._active('lio-adapter'):raise ValueError('owned active simulation SLAM required')
                if action=='tf_fault_on':(self.directory/'fault-tf').touch(mode=0o600)
                else:(self.directory/'fault-tf').unlink(missing_ok=True)
            elif action=='save':return self.save(payload.get('name'))
            elif action=='maps':return dict(maps=self.catalog.list())
            elif action=='load':return self.load(payload.get('map_id'))
            elif action=='rviz_start':return self.rviz()
            elif action=='loaded_rviz_start':return self.rviz(True)
            elif action=='relocated_rviz_start':return self.rviz(relocated=True)
            elif action=='rviz_stop':
                self.parent._stop('slam-rviz');self.parent._stop('slam-observer')
            elif action!='status':raise ValueError('unregistered SLAM tool operation')
            return self.snapshot()

    def save(self,name):
        p=self.parent
        with p.lock:
            status=self.snapshot()
            if not status['online']:raise ValueError('fresh admitted LIO map required')
            raw=status['state']
            if not raw.get('map_reference'):raise ValueError('waiting for first filtered map export')
            reference=DataReference(**dict(raw['map_reference'],dimensions=tuple(raw['map_reference']['dimensions'])))
            if raw.get('map',{}).get('error'):raise ValueError('map accumulation failed: '+raw['map']['error'])
            if not p.config.get('scene_id'):raise ValueError('recording lacks admitted scene provenance; map saving rejected')
            data=StreamReader(self.directory/'payloads',slots=4).load(reference)
            sensor=p.config
            # Snapshot the parameters actually used at process launch. Editing
            # a template while mapping must not relabel an old map's algorithm.
            algorithm=json.loads((self.directory/'fast-lio.yaml').read_text())['/**']['ros__parameters']
            algorithm['common'].pop('lid_topic',None);algorithm['common'].pop('imu_topic',None)
            return self.catalog.save(name,data,dict(vehicle=sensor['kind'],sensor=sensor,
                world=dict(scene=p.config['scene_id'],gazebo_world=sensor['world'],session=p.child.owner.partition,vehicle=p.child.id,source=self.source),
                algorithm=dict(name='FAST-LIO2',lock=json.loads((p.root/'simulation/dependencies/mid360-slam.lock.json').read_text()),
                    config=algorithm,map_limits=self.config['map_limits'],config_sha256=hashlib.sha256(json.dumps(algorithm,sort_keys=True).encode()).hexdigest()),
                frame_id=self.config['frames']['map'],frame_epoch=self.config['generation'],
                source_capture_ros_ns=raw['map_export_capture_ros_ns'],created_at=self.config['created_at']))

    def pause(self,value):
        if not self.directory or not self.parent._active('lio-adapter'):raise ValueError('start SLAM first')
        path=self.directory/'pause'
        if value:path.touch(mode=0o600)
        else:path.unlink(missing_ok=True)
        return dict(paused=value,scope='map accumulation only; FAST-LIO estimation continues')
