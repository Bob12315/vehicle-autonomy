"""Finite recorded virtual-camera timeline with a bounded asynchronous YOLO worker."""
from datetime import datetime,timezone,timedelta
import hashlib,json
from pathlib import Path
from threading import Event,Lock,Thread
import time
from uuid import uuid4
from contracts.core.primitives import SchemaVersion
from contracts.core.quality import QualityState
from contracts.core.time import TimePoint
from contracts.sensor import Observation,DetectedObject
from perception.vision.projection import PlaneCalibration
from perception.vision.yolox import YoloXDetector

class RecordedVisionSource:
    def __init__(self,path,clock_domain):
        if not path.is_file():raise ValueError('regular recording manifest required; no physical camera input')
        d=json.loads(path.read_text());base=path.parent
        if set(d)!={'schema','kind','source','model','model_sha256','calibration','frames','class_map','threshold'} or d['schema']!=1 or d['kind']!='recorded_virtual_camera' or not d['source']:raise ValueError('explicit recorded camera schema/provenance required')
        self.frames=d['frames'];self.base=base;self.domain=clock_domain;self.class_map=d['class_map'];self.threshold=d['threshold']
        if not self.frames or len(self.frames)>2000 or any(set(f)!={'pts_ns','path','sha256'} or type(f['pts_ns']) is not int or f['pts_ns']<0 for f in self.frames) or any(b['pts_ns']<=a['pts_ns'] for a,b in zip(self.frames,self.frames[1:])):raise ValueError('strict finite recording timeline required')
        if not self.class_map or any(not k.isdigit() or v not in ('bucket_1','bucket_2','bucket_3') for k,v in self.class_map.items()):raise ValueError('explicit visual class mapping required')
        self.calibration=None if d['calibration'] is None else PlaneCalibration.load(base/d['calibration'])
        self.detector=YoloXDetector(base/d['model'],d['model_sha256'],self.threshold)
        version=hashlib.sha256(path.read_bytes()+(b'unlocated' if self.calibration is None else self.calibration.version.encode())).hexdigest()
        self.producer='vision.recorded:'+version[:16]+':'+uuid4().hex
        self.pixel_observations=();self.known={}
        self.start_ns=None;self.index=0;self.sequence=0;self._pending=None;self._output=None;self.lock=Lock();self.stop=Event()
        self.health={'kind':d['kind'],'source':d['source'],'version':version,'calibration':None if self.calibration is None else self.calibration.version,'error':None,'frames':0,'dropped':0,'unlocated':0,'latency_ns':None,'eos':False,'frame':'camera_optical','exposure_ns':0,'exposure_source':'instantaneous synthetic plane-camera recording; physical photograph exposure unknown','captured_ns':None,'frame_received_ns':None,'inference_finished_ns':None,'class_map':dict(self.class_map)}
        self.thread=Thread(target=self._work,daemon=True);self.thread.start()
    def poll(self,now):
        if self.start_ns is None:self.start_ns=now.monotonic_ns
        with self.lock:
            selected=None
            while self.index<len(self.frames) and self.start_ns+self.frames[self.index]['pts_ns']<=now.monotonic_ns:
                if selected is not None:self.health['dropped']+=1
                selected=self.frames[self.index];self.index+=1
            if selected is not None:
                if self._pending is not None:self.health['dropped']+=1
                capture_ns=self.start_ns+selected['pts_ns']
                capture=TimePoint(capture_ns,now.utc+timedelta(microseconds=(capture_ns-now.monotonic_ns)//1000),self.domain)
                self._pending=(selected,capture,now)
            self.health['eos']=self.index==len(self.frames)
            output,self._output=self._output,None
        return () if output is None else output
    def _work(self):
        import cv2
        while not self.stop.wait(.005):
            with self.lock:packet,self._pending=self._pending,None
            if packet is None:continue
            frame,capture,received=packet
            try:
                image_path=self.base/frame['path']
                if not image_path.is_file():raise ValueError('regular recorded image required; no device input')
                if hashlib.sha256(image_path.read_bytes()).hexdigest()!=frame['sha256']:raise ValueError('recording image hash mismatch')
                image=cv2.imread(str(image_path));detections=self.detector.detect(image)
                finished=time.monotonic_ns();latency=finished-capture.monotonic_ns
                output=[];pixels=[];seen=set()
                mapped=[d for d in detections if str(d.class_id) in self.class_map and d.confidence>=self.threshold]
                ambiguous={d.class_id for d in mapped if sum(other.class_id==d.class_id for other in mapped)>1}
                for detection in detections:
                    self.sequence+=1
                    pixels.append(Observation(f'{self.producer}:pixel:{self.sequence}',SchemaVersion(1,0),self.producer,self.sequence,capture,
                        TimePoint(finished,datetime.now(timezone.utc),self.domain),QualityState.VALID if 0<=latency<=1_000_000_000 else QualityState.INVALID,detection,'camera_optical'))
                    label=self.class_map.get(str(detection.class_id))
                    if label is None or detection.confidence<self.threshold:continue
                    if self.calibration is None or detection.class_id in ambiguous:
                        self.health['unlocated']+=1;continue
                    try:position=self.calibration.project(detection,(image.shape[1],image.shape[0]))
                    except ValueError:self.health['unlocated']+=1;continue
                    seen.add(detection.class_id);self.known[detection.class_id]=position
                    self.sequence+=1
                    output.append(Observation(f'{self.producer}:{self.sequence}',SchemaVersion(1,0),self.producer,self.sequence,capture,
                        TimePoint(finished,datetime.now(timezone.utc),self.domain),QualityState.VALID if 0<=latency<=1_000_000_000 else QualityState.INVALID,
                        DetectedObject('class_'+str(detection.class_id),label,position,detection.confidence),'odom'))
                for class_id,position in self.known.items():
                    if class_id in seen:continue
                    self.sequence+=1
                    output.append(Observation(f'{self.producer}:{self.sequence}',SchemaVersion(1,0),self.producer,self.sequence,capture,
                        TimePoint(finished,datetime.now(timezone.utc),self.domain),QualityState.UNAVAILABLE,
                        DetectedObject('class_'+str(class_id),self.class_map[str(class_id)],position,0.0),'odom'))
                with self.lock:
                    self.pixel_observations=tuple(pixels)
                    self.health.update(captured_ns=capture.monotonic_ns,frame_received_ns=received.monotonic_ns,inference_finished_ns=finished)
                    self.health['frames']+=1;self.health['latency_ns']=latency
                    self._output=tuple(output)
            except Exception as exc:
                with self.lock:self.health['error']=f'{type(exc).__name__}: {exc}';self._output=()
    def close(self):
        self.stop.set();self.thread.join(timeout=2)
        if self.thread.is_alive():raise RuntimeError('vision worker shutdown unconfirmed')
