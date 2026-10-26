"""Independent real YOLOX process over bounded original camera references.

Inference never runs on the vehicle/Authority owner. No ROS or vehicle writer.
"""
import argparse
from collections import deque
from dataclasses import replace
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import signal
from threading import Event,RLock,Thread
import time
from uuid import uuid4

from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.streams import DataKind,SourceKind,FrameDescriptor,StreamObservation
from vehicle_autonomy.world.mapping.grid import atomic_json
from vehicle_autonomy.world.model.stream_input import observation
from vehicle_autonomy.world.sensors.stream_store import StreamStore,StreamReader
from vehicle_autonomy.world.perception.vision.yolox import YoloXDetector

COCO=('person','bicycle','car','motorcycle','airplane','bus','train','truck','boat','traffic light','fire hydrant','stop sign','parking meter','bench','bird','cat','dog','horse','sheep','cow','elephant','bear','zebra','giraffe','backpack','umbrella','handbag','tie','suitcase','frisbee','skis','snowboard','sports ball','kite','baseball bat','baseball glove','skateboard','surfboard','tennis racket','bottle','wine glass','cup','fork','knife','spoon','bowl','banana','apple','sandwich','orange','broccoli','carrot','hot dog','pizza','donut','cake','chair','couch','potted plant','bed','dining table','toilet','tv','laptop','mouse','remote','keyboard','cell phone','microwave','oven','toaster','sink','refrigerator','book','clock','vase','scissors','teddy bear','hair drier','toothbrush')


def read_state(root):
    fd=os.open(Path(root)/'state.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:raw=os.read(fd,262145)
    finally:os.close(fd)
    if len(raw)>262144:raise ValueError('camera metadata budget')
    return json.loads(raw)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);a=p.parse_args();c=json.loads(a.config.read_text())
    if set(c)!={'schema','directory','camera_directory','camera_source','camera_generation','source_id','frame_epoch','calibration_version','model_path','model_sha256'} or c['schema']!=1:raise ValueError('strict pinned detector profile required')
    import cv2
    import numpy as np
    stop=Event();lock=RLock();epoch=uuid4().hex;root=Path(c['directory']);root.mkdir(mode=0o700,parents=True,exist_ok=True)
    store=StreamStore(root/'payloads',slots=4,max_bytes=2_000_000);reader=StreamReader(Path(c['camera_directory'])/'payloads')
    state={'streams':{},'counts':{},'input_frames_skipped':0,'inference_in_flight':False};latencies=deque(maxlen=256);end_times=deque(maxlen=256);fault=None
    def finish(*_):stop.set()
    signal.signal(signal.SIGTERM,finish);signal.signal(signal.SIGINT,finish)
    def camera():
        value=read_state(c['camera_directory']);now=time.monotonic_ns()
        if value['error'] is not None or value['source_id']!=c['camera_source'] or value['generation']!=c['camera_generation'] or not 0<=now-value['published_ns']<=500_000_000:raise ValueError('camera unavailable or changed epoch')
        item=observation(value['streams']['camera']);h=item.header
        if (h.kind,h.source_kind,h.calibration_version,h.frame.frame_id,h.frame.origin_id)!=(DataKind.IMAGE,SourceKind.SIMULATION,c['calibration_version'],'camera_optical',c['frame_epoch']):raise ValueError('camera provenance/profile mismatch')
        if h.captured_at is None or h.captured_at.clock_domain_id!='host-monotonic-simulation' or not 0<=now-h.captured_at.monotonic_ns<=500_000_000:raise ValueError('original camera sample expired')
        return item
    def heartbeat():
        while not stop.wait(.1):
            error=fault
            try:camera()
            except (OSError,ValueError,KeyError,TypeError) as exc:error=type(exc).__name__+': '+str(exc)
            with lock:
                data={**state,'streams':dict(state['streams']),'counts':dict(state['counts'])};samples=sorted(latencies)
                if not data['streams']:error=error or 'waiting for actual inference'
                elif time.monotonic_ns()-data['streams']['detections']['header']['captured_at']['monotonic_ns']>=2_000_000_000:error=error or 'inference result expired/stalled'
                performance=dict(samples=len(samples),inference_p50_ns=None if not samples else samples[len(samples)//2],inference_p95_ns=None if not samples else samples[min(len(samples)-1,int(len(samples)*.95))],yolo_fps=0. if len(end_times)<2 else (len(end_times)-1)*1e9/(end_times[-1]-end_times[0]),sample_capacity=256)
            atomic_json(root/'state.json',dict(schema=1,generation=epoch,source_kind='simulation',source_id=c['source_id'],origin_id=c['frame_epoch'],ap_world_epoch=c['frame_epoch'],published_ns=time.monotonic_ns(),error=error,performance=performance,backend='opencv_dnn_cpu',model_sha256=c['model_sha256'],**data))
    thread=Thread(target=heartbeat,name='perception-heartbeat',daemon=True);thread.start()
    last=None
    try:
        detector=YoloXDetector(Path(c['model_path']),c['model_sha256'],threshold=.5)
        while not stop.wait(.02):
            try:
                item=camera();h=item.header
                if last is not None and h.sequence<=last.sequence:
                    if h.sequence<last.sequence:raise ValueError('camera source regressed')
                    continue
                if last is not None and (h.source_timestamp_ns<=last.source_timestamp_ns or h.source_clock_domain!=last.source_clock_domain):raise ValueError('camera source time regressed')
                raw=reader.load(item.data);height,width,channels=item.data.dimensions
                if channels!=3 or item.data.media_type not in ('application/x-raw-rgb8','application/x-raw-bgr8'):raise ValueError('actual RGB/BGR camera required')
                pixels=np.frombuffer(raw,dtype=np.uint8).reshape(height,width,3)
                bgr=cv2.cvtColor(pixels,cv2.COLOR_RGB2BGR) if item.data.media_type=='application/x-raw-rgb8' else pixels.copy()
                with lock:state['inference_in_flight']=True
                began=time.monotonic_ns()
                detected=sorted(detector.detect(bgr),key=lambda d:d.confidence,reverse=True)[:128];ended=time.monotonic_ns()
                received=TimePoint(ended,datetime.now(timezone.utc),'host-monotonic-simulation')
                boxes=[dict(class_id=d.class_id,label=COCO[d.class_id],confidence=d.confidence,xyxy=list(d.xyxy)) for d in detected]
                body=dict(schema=1,detections=boxes,primary_label=boxes[0]['label'] if boxes else None,detected=bool(boxes),image_header=to_json_value(h),image_reference=to_json_value(item.data),captured_at=to_json_value(h.captured_at),source_frame=h.frame.frame_id,model_id='opencv-zoo-yolox-2022nov',model_version=c['model_sha256'],inference_backend='opencv_dnn_cpu',opencv_version=cv2.__version__,inference_ns=ended-began,inference_started_ns=began,completed_ns=ended,world_positions_available=False)
                ref=store.put(json.dumps(body,separators=(',',':'),allow_nan=False).encode(),'application/vnd.vehicle-autonomy.image-detections',channel='detections')
                header=replace(h,source_id=c['source_id'],sensor_id='detections',kind=DataKind.DETECTIONS,generation=epoch,received_at=received,frame=FrameDescriptor('camera_optical','image_pixels',c['frame_epoch'],units='pixels'),confidence=max((d.confidence for d in detected),default=0.))
                for d in detected:
                    x0,y0,x1,y1=map(int,d.xyxy);cv2.rectangle(bgr,(x0,y0),(x1,y1),(0,255,0),2)
                ok,jpeg=cv2.imencode('.jpg',bgr,[cv2.IMWRITE_JPEG_QUALITY,80])
                if not ok:raise ValueError('preview encode failed')
                preview=store.put(jpeg.tobytes(),'image/jpeg',(height,width,3),channel='preview')
                with lock:
                    state['streams']={'detections':to_json_value(StreamObservation(header,ref)),'preview':to_json_value(StreamObservation(replace(header,sensor_id='preview',kind=DataKind.IMAGE,frame=h.frame),preview))}
                    state['counts']['inference']=state['counts'].get('inference',0)+1
                    state['input_frames_skipped']+=max(0,h.sequence-last.sequence-1) if last is not None else 0
                    state['inference_in_flight']=False;latencies.append(ended-began);end_times.append(ended)
                last=h
            except (OSError,ValueError,KeyError,TypeError):
                with lock:state['inference_in_flight']=False
                stop.wait(.05)
    except BaseException as exc:
        fault=type(exc).__name__+': detector failed';raise
    finally:
        stop.set();thread.join(2)
        atomic_json(root/'stopped.json',dict(stopped=True,generation=epoch,at_ns=time.monotonic_ns()))


if __name__=='__main__':main()
