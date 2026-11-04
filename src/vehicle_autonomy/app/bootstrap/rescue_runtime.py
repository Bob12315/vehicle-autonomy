"""Explicit owned-rescue sensor and non-vehicle payload composition.

Vehicle motion retains the original Execution/Safety/sole writer. PT inference
runs in a separate configured environment and can neither read nor send commands.
"""
from dataclasses import replace
from collections import deque
import hashlib,json,os,re,subprocess,time
from pathlib import Path
from uuid import uuid4

from vehicle_autonomy import __file__ as package_file
from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment
from vehicle_autonomy.contracts.core.primitives import SchemaVersion
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.core.geometry import Vector3
from vehicle_autonomy.contracts.sensor import Observation,DetectedObject
from vehicle_autonomy.engine.control.payload_execution import PayloadExecution,PayloadSafetyPolicy
from vehicle_autonomy.world.mapping.grid import atomic_json


def validate_result(value,*,digest,topic,generation,now_ns):
    fields={'schema','worker_epoch','world_generation','camera_source','sequence','captured_ns','received_ns','model_sha256','backend','marker_backend','objects','error'}
    if type(value) is not dict or set(value)!=fields or type(value['schema']) is not int or value['schema']!=1:
        raise ValueError('strict rescue detection envelope required')
    if (value['model_sha256']!=digest or value['camera_source']!=topic or value['world_generation']!=generation
            or value['backend']!='ultralytics_pt' or value['marker_backend']!='yellow_disc_h_shape_v1' or value['error'] is not None
            or not isinstance(value['worker_epoch'],str) or re.fullmatch('[0-9a-f]{32}',value['worker_epoch']) is None):
        raise ValueError('rescue detector provenance mismatch')
    if (any(type(value[k]) is not int for k in ('sequence','captured_ns','received_ns')) or value['sequence']<1
            or not 0<=now_ns-value['captured_ns']<=1_000_000_000
            or not value['captured_ns']<=value['received_ns']<=now_ns):
        raise ValueError('rescue detector original capture/deadline invalid')
    if type(value['objects']) is not list or len(value['objects'])>128:raise ValueError('rescue detection count budget')
    result=[];identities=set()
    for item in value['objects']:
        if type(item) is not dict or set(item)!={'id','label','position','confidence','xyxy','detector'}:
            raise ValueError('strict rescue object required')
        if (not isinstance(item['id'],str) or re.fullmatch(r'target-[1-9][0-9]{0,8}',item['id']) is None
                or item['id'] in identities or item['label'] not in ('bucket','H')
                or item['detector'] not in ('pt','h_marker') or item['detector']=='h_marker' and item['label']!='H'
                or type(item['confidence']) not in (int,float) or not .3<=item['confidence']<=1
                or type(item['position']) is not list or len(item['position'])!=3):
            raise ValueError('rescue object identity/class/confidence invalid')
        point=Vector3(*item['position'])
        if not -5<=point.x<=5 or not -2<=point.y<=62 or not -.2<=point.z<=.4:
            raise ValueError('rescue target outside declared field')
        from vehicle_autonomy.world.perception.vision.yolox import PixelDetection
        box=PixelDetection(0,item['confidence'],tuple(item['xyxy']))
        if not 0<=box.xyxy[0]<box.xyxy[2]<=640 or not 0<=box.xyxy[1]<box.xyxy[3]<=480:
            raise ValueError('rescue detection outside actual camera')
        identities.add(item['id']);result.append((item,point))
    return result


class RescueRuntime:
    def __init__(self,runtime,ownership):
        limits=runtime.profile.safety;manifest=ownership.manifest
        if (runtime.profile.kind!='copter' or manifest.get('rescue_2026',{}).get('definition_id')!='copter_rescue'
                or manifest['rescue_2026'].get('fingerprint')!=manifest.get('fixed_vehicle',{}).get('fingerprint')
                or (limits.min_x_m,limits.max_x_m,limits.min_y_m,limits.max_y_m,limits.max_takeoff_m)!=(-5.,5.,-2.,62.,5.)):
            raise ValueError('explicit owned rescue model and bounded rescue Safety profile required')
        from vehicle_autonomy.actions.devices.gazebo_payload import GazeboPayloadPort
        profile=json.loads((resource_root()/'configs/perception/rescue_2026_pt.json').read_text())
        if profile['schema']!=1 or profile['classes']!=['bucket','H'] or profile['imgsz']!=640 or profile['marker_backend']!='yellow_disc_h_shape_v1':
            raise ValueError('reviewed bucket/H 640-pixel detector profile required')
        host=HostEnvironment();python=host.path('vision_python');model=host.path('rescue_model')
        if python is None or not python.is_file() or model is None or not model.is_file():raise ValueError('configure local vision_python and rescue_model through HostEnvironment')
        host.verify(model);self.digest=hashlib.sha256(model.read_bytes()).hexdigest()
        if self.digest!=profile['model_sha256']:raise ValueError('rescue model differs from the trained versioned detector profile')
        self.root=ownership.path.parent/'rescue-inference';self.root.mkdir(mode=0o700)
        self.runtime=runtime;self.ownership=ownership;self.last=0;self.sequence=0;self.worker_epoch=None;self.last_pose=0
        self.observations=deque(maxlen=256)
        self.latest_capture=None;self.latest_count=0;self.last_error='waiting for PT inference'
        self.topic=f'/vaf/camera/{ownership.world}/{ownership.model}/gimbal-camera/image'
        self.config=dict(model_path=str(model),model_sha256=self.digest,device=profile['device'],confidence=profile['confidence'],iou=profile['iou'],camera_topic=self.topic,
            camera_packet=str(ownership.path.parent/'camera-gimbal-camera/latest.packet'))
        atomic_json(self.root/'config.json',self.config)
        env=host.process_environment();env['PYTHONPATH']=str(Path(package_file).resolve().parent.parent)
        env['YOLO_CONFIG_DIR']=str(self.root/'ultralytics')
        self.log=(self.root/'worker.log').open('wb')
        self.port=GazeboPayloadPort(ownership.model)
        try:
            self.process=subprocess.Popen([str(python),'-m','vehicle_autonomy.world.perception.vision.rescue_worker',
                '--config',str(self.root/'config.json')],cwd=self.root,env=env,stdout=self.log,stderr=subprocess.STDOUT)
        except BaseException:
            self.port.close();self.log.close();raise
        self.execution=PayloadExecution(runtime.authority,self.port,PayloadSafetyPolicy(('vision.pt:',),allowed_labels=('bucket',),
            max_alignment_m=.3,max_speed_mps=.08,min_release_height_m=.5,max_release_height_m=1.5),runtime._world,
            observation_validator=self.known_observation)
    def known_observation(self,effect,now):
        world=self.runtime.world_snapshot()
        if world is None or world.environment!=effect.environment:return False
        for observation,generation,environment in self.observations:
            if (generation==world.version.generation_id and environment==effect.environment
                    and str(observation.producer_id)+':'+str(observation.data.object_id)==effect.target_id
                    and str(observation.producer_id)==effect.producer_id
                    and str(observation.observation_id)==effect.target_observation_id
                    and observation.captured_at==effect.target_captured_at and observation.data.position==effect.target_position
                    and 0<=now.elapsed_ns_since(observation.captured_at)<=1_000_000_000):return True
        return False
    def poll(self):
        world=self.runtime.world_snapshot();now=self.runtime.clock()
        if world is None:return
        loc=world.localization
        if (loc is not None and loc.quality is QualityState.VALID and world.vehicle is not None
                and world.vehicle.health.quality is QualityState.VALID
                and 0<=now.elapsed_ns_since(loc.pose.captured_at)<=1_000_000_000
                and now.monotonic_ns-self.last_pose>=100_000_000):
            p=loc.pose.value.position;q=loc.pose.value.orientation
            atomic_json(self.root/'pose.json',dict(published_ns=now.monotonic_ns,captured_ns=loc.pose.captured_at.monotonic_ns,
                world_generation=str(world.version.generation_id),position=[p.x,p.y,p.z],orientation=[q.x,q.y,q.z,q.w]))
            self.last_pose=now.monotonic_ns
        try:
            path=self.root/'detections.json'
            with path.open('rb') as stream:raw=stream.read(65537)
            if len(raw)>65536:raise ValueError('detection result budget')
            d=json.loads(raw)
            if self.process.poll() is not None:raise ValueError('rescue detector stopped')
            entries=validate_result(d,digest=self.digest,topic=self.topic,generation=str(world.version.generation_id),now_ns=now.monotonic_ns)
            self.latest_capture=d['captured_ns'];self.latest_count=len(entries);self.last_error=None
            if self.worker_epoch is not None and self.worker_epoch!=d['worker_epoch']:raise ValueError('rescue detector epoch changed')
            self.worker_epoch=d['worker_epoch']
            if d['sequence']>self.last:
                for item,point in entries:
                    producer=('vision.pt:' if item['detector']=='pt' else 'vision.marker:')+self.worker_epoch
                    self.sequence+=1
                    observation=Observation(producer+':'+str(self.sequence),SchemaVersion(1,0),producer,self.sequence,
                        replace(now,monotonic_ns=d['captured_ns']),replace(now,monotonic_ns=d['received_ns']),QualityState.VALID,
                        DetectedObject(item['id'],item['label'],point,item['confidence']),'odom')
                    self.runtime.ingest_observation(observation)
                    self.observations.append((observation,world.version.generation_id,world.environment))
                self.last=d['sequence']
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.last_error=(type(exc).__name__+': '+str(exc))[:180]
        for observation in self.port.poll(now):self.runtime.ingest_observation(observation)
        self.execution.tick(now)
    def health(self):
        age=None if self.latest_capture is None else self.runtime.clock().monotonic_ns-self.latest_capture
        online=self.process.poll() is None and age is not None and 0<=age<=1_000_000_000 and self.last_error is None
        return dict(backend='ultralytics_pt',model_sha256=self.digest,online=online,
            capture_age_ns=age,object_count=self.latest_count,error=self.last_error)
    def close(self):
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
        finally:self.port.close();self.log.close()
