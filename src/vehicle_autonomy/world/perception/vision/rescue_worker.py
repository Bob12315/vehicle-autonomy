"""Explicit PT inference process over a pinned owned camera and telemetry cut.

No Gazebo truth, MAVLink, vehicle commands or SEND authority enter this process.
"""
import argparse
import json,signal,time
from collections import deque
from pathlib import Path
from uuid import uuid4

from vehicle_autonomy.world.mapping.grid import atomic_json
from vehicle_autonomy.world.sensors.camera.packet import decode,MAX_PACKET
from .ultralytics_pt import PtDetector
from .rescue_geometry import project
from .landing_marker import detect_h,overlap
from .preview import annotated_packet
from .association import TargetAssociator
from vehicle_autonomy.world.sensors.camera.motion import match_motion,MotionPending
from vehicle_autonomy.world.sensors.camera.virtual_nadir import VirtualNadir,validate_config
from vehicle_autonomy.world.sensors.camera.live import atomic
from vehicle_autonomy.world.sensors.camera.packet import encode


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    c=json.loads(a.config.read_text());root=a.config.parent;stop=False
    def finish(*_):
        nonlocal stop;stop=True
    signal.signal(signal.SIGTERM,finish);signal.signal(signal.SIGINT,finish)
    import cv2,numpy as np
    detector=PtDetector(c['model_path'],c['model_sha256'],device=c['device'],threshold=c['confidence'],iou=c['iou'])
    settings=validate_config(c['virtual_nadir']);rectifier=VirtualNadir()
    epoch=uuid4().hex;last=0;associator=TargetAssociator();motion_key=None;fault_count=0;faults=deque(maxlen=32);previous_fault=None
    while not stop:
        try:
            with (root/'pose.json').open('rb') as stream:pose_data=stream.read(65537)
            if len(pose_data)>65536:raise ValueError('camera motion history budget')
            pose=json.loads(pose_data);now=time.monotonic_ns()
            packet=Path(c['camera_packet'])
            with packet.open('rb') as stream:raw=stream.read(MAX_PACKET+1)
            if len(raw)>MAX_PACKET:raise ValueError('camera packet budget')
            meta,jpeg=decode(raw)
            if meta['source']!=c['camera_topic'] or meta['capture_clock']!='gazebo-simulation':raise ValueError('camera source changed')
            seq=meta['sequence']
            if seq==last:
                if now-capture_from_metadata(meta)>500_000_000:raise ValueError('original camera stopped')
                time.sleep(.02);continue
            if seq<last:raise RuntimeError('owned camera sequence regressed')
            capture=capture_from_metadata(meta)
            matched=match_motion(pose,capture,now,expected_key=motion_key,
                max_distance_ns=int(settings['max_sample_distance_ms']*1e6),
                max_span_ns=int(settings['max_bracket_span_ms']*1e6),min_attitude_rate_hz=settings['min_attitude_rate_hz'])
            motion_key=matched.key
            image=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
            if image is None or image.shape[:2]!=(480,640):raise ValueError('calibrated image size mismatch')
            current=matched.pose;rectify_started=time.monotonic_ns();rectified=rectifier.rectify(image,matched)
            rectify_ms=(time.monotonic_ns()-rectify_started)/1e6
            image=rectified.image
            rectification=dict(valid=True,**rectified.camera.metadata(),attitude_rate_hz=matched.attitude_rate_hz,
                attitude_bracket_ns=list(matched.attitude_bracket_ns),position_bracket_ns=list(matched.position_bracket_ns),
                body_orientation_flu_enu=[current.orientation.x,current.orientation.y,current.orientation.z,current.orientation.w],
                valid_fraction=float(np.count_nonzero(rectified.valid_mask)/rectified.valid_mask.size),rectify_ms=rectify_ms)
            began=time.monotonic_ns()
            neural=detector.detect(image);markers=detect_h(image)
            detected=[(d,'pt') for d in neural if not any(overlap(d.xyxy,m.xyxy)>.4 for m in markers)]
            detected.extend((d,'h_marker') for d in markers)
            detected=[(d,backend) for d,backend in detected if rectified.accepts(d.xyxy)]
            ended=time.monotonic_ns();values=[];projected=[]
            if ended-capture>1_000_000_000:raise ValueError('inference deadline exceeded')
            for d,backend in sorted(detected,key=lambda item:-item[0].confidence):
                label=detector.names[d.class_id]
                try:point=project(d,current,label,virtual_camera=rectified.camera)
                except ValueError:continue
                projected.append((point,label,backend,d))
            identifiers=associator.update([(point,label,backend) for point,label,backend,d in projected],ended)
            for key,(point,label,backend,d) in zip(identifiers,projected):
                values.append(dict(id=key,label=label,position=[point.x,point.y,point.z],confidence=d.confidence,xyxy=list(d.xyxy),detector=backend))
            atomic_json(root/'detections.json',dict(schema=2,worker_epoch=epoch,world_generation=pose['world_generation'],
                camera_source=c['camera_topic'],sequence=seq,captured_ns=capture,received_ns=ended,
                image_domain='virtual_nadir',calibration_id=settings['calibration_id'],reference_id=rectifier.reference_id,
                model_sha256=c['model_sha256'],backend='ultralytics_pt',marker_backend='yellow_disc_h_shape_v1',objects=values,error=None))
            atomic_json(root/'health.json',dict(error=None,published_ns=ended,captured_ns=capture,
                inference_ns=ended-now,object_count=len(values),backend='ultralytics_pt',worker_epoch=epoch,
                reference_id=rectifier.reference_id,rectification_valid=True,
                stabilization=dict(rectification,fault_count=fault_count,last_fault=faults[-1] if faults else None)))
            previous_fault=None
            last=seq
            try:
                preview=annotated_packet(image,meta,detected,detector.names,epoch=epoch,
                    world_generation=pose['world_generation'],model_sha256=c['model_sha256'],
                    captured_host_ns=capture,started_ns=began,completed_ns=ended,rectification=rectification)
                header,_=decode(preview)
                header.update(kind='stabilized',display_name='增稳画面',frame_role='virtual_nadir',detections=[])
                display=image.copy()
                cv2.rectangle(display,(0,0),(639,28),(25,30,35),-1)
                cv2.putText(display,'VIRTUAL NADIR | YAW LOCKED',(8,20),cv2.FONT_HERSHEY_SIMPLEX,.5,(240,245,240),1,cv2.LINE_AA)
                ok,jpeg_stable=cv2.imencode('.jpg',display,[cv2.IMWRITE_JPEG_QUALITY,85])
                if not ok:raise ValueError('virtual camera preview encode failed')
                atomic(root/'stabilized.packet',encode(header,jpeg_stable.tobytes()))
                atomic(root/'preview.packet',preview)
            except (OSError,ValueError,TypeError) as exc:
                # An optional display fault cannot change the adopted
                # inference result or stop the perception producer.
                atomic_json(root/'preview-health.json',dict(error=str(exc),published_ns=time.monotonic_ns()))
        except MotionPending:
            time.sleep(.01)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            # The owner invalidates observations immediately. Association keeps
            # only bounded identity candidates; recovery needs new qualified
            # detections. Motion/reference epochs remain pinned above.
            if str(exc)!=previous_fault:
                fault_count+=1;faults.append(dict(error=str(exc),at_ns=time.monotonic_ns(),last_sequence=last))
                atomic_json(root/'faults.json',list(faults));previous_fault=str(exc)
            atomic_json(root/'health.json',dict(error=str(exc),published_ns=time.monotonic_ns(),
                worker_epoch=epoch,reference_id=rectifier.reference_id,rectification_valid=False))
            time.sleep(.05)
    return 0


def capture_from_metadata(metadata):
    return metadata['clock_host_ns']+metadata['captured_ns']-metadata['clock_sim_ns']


if __name__=='__main__':raise SystemExit(main())
