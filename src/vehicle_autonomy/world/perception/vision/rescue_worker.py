"""Explicit PT inference process over a pinned owned camera and telemetry cut.

No Gazebo truth, MAVLink, vehicle commands or SEND authority enter this process.
"""
import argparse
from datetime import datetime,timezone
import hashlib,json,signal,time
from pathlib import Path
from uuid import uuid4

from vehicle_autonomy.contracts.core.geometry import Pose3,Quaternion,Vector3
from vehicle_autonomy.world.mapping.grid import atomic_json
from vehicle_autonomy.world.sensors.camera.packet import decode,MAX_PACKET
from .ultralytics_pt import PtDetector
from .rescue_geometry import project
from .landing_marker import detect_h,overlap


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    c=json.loads(a.config.read_text());root=a.config.parent;stop=False
    def finish(*_):
        nonlocal stop;stop=True
    signal.signal(signal.SIGTERM,finish);signal.signal(signal.SIGINT,finish)
    import cv2,numpy as np
    detector=PtDetector(c['model_path'],c['model_sha256'],device=c['device'],threshold=c['confidence'],iou=c['iou'])
    epoch=uuid4().hex;last=0;tracks={};number=0
    while not stop:
        try:
            pose=json.loads((root/'pose.json').read_text());now=time.monotonic_ns()
            if not 0<=now-pose['published_ns']<=500_000_000:raise ValueError('telemetry cut stale')
            packet=Path(c['camera_packet'])
            with packet.open('rb') as stream:raw=stream.read(MAX_PACKET+1)
            if len(raw)>MAX_PACKET:raise ValueError('camera packet budget')
            meta,jpeg=decode(raw)
            if meta['source']!=c['camera_topic'] or meta['capture_clock']!='gazebo-simulation':raise ValueError('camera source changed')
            seq=meta['sequence']
            if seq==last:time.sleep(.02);continue
            if seq<last:raise RuntimeError('owned camera sequence regressed')
            capture=meta['clock_host_ns']+meta['captured_ns']-meta['clock_sim_ns']
            if not 0<=now-capture<=500_000_000 or abs(capture-pose['captured_ns'])>250_000_000:raise ValueError('unsynchronized/stale camera and telemetry')
            image=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
            if image is None or image.shape[:2]!=(480,640):raise ValueError('calibrated image size mismatch')
            current=Pose3(Vector3(*pose['position']),Quaternion(*pose['orientation']))
            neural=detector.detect(image);markers=detect_h(image)
            detected=[(d,'pt') for d in neural if not any(overlap(d.xyxy,m.xyxy)>.4 for m in markers)]
            detected.extend((d,'h_marker') for d in markers)
            ended=time.monotonic_ns();values=[];used=set()
            if ended-capture>1_000_000_000:raise ValueError('inference deadline exceeded')
            for d,backend in sorted(detected,key=lambda item:-item[0].confidence):
                label=detector.names[d.class_id]
                try:point=project(d,current,label)
                except ValueError:continue
                choices=[(sum((a-b)**2 for a,b in zip((point.x,point.y),value[:2])),key) for key,value in tracks.items()
                    if key not in used and value[2]==label and value[4]==backend and ended-value[3]<2_000_000_000]
                closest=min(choices,default=(float('inf'),None))
                if closest[0]<.5**2:key=closest[1]
                else:number+=1;key='target-'+str(number)
                used.add(key);tracks[key]=(point.x,point.y,label,ended,backend)
                values.append(dict(id=key,label=label,position=[point.x,point.y,point.z],confidence=d.confidence,xyxy=list(d.xyxy),detector=backend))
            tracks={k:v for k,v in tracks.items() if ended-v[3]<2_000_000_000}
            atomic_json(root/'detections.json',dict(schema=1,worker_epoch=epoch,world_generation=pose['world_generation'],
                camera_source=c['camera_topic'],sequence=seq,captured_ns=capture,received_ns=ended,
                model_sha256=c['model_sha256'],backend='ultralytics_pt',marker_backend='yellow_disc_h_shape_v1',objects=values,error=None))
            atomic_json(root/'health.json',dict(error=None,published_ns=ended,captured_ns=capture,
                inference_ns=ended-now,object_count=len(values),backend='ultralytics_pt'))
            last=seq
        except (OSError,ValueError,KeyError,TypeError) as exc:
            atomic_json(root/'health.json',dict(error=str(exc),published_ns=time.monotonic_ns()))
            time.sleep(.05)
    return 0


if __name__=='__main__':raise SystemExit(main())
