"""Owned PT consumer of an independent attitude-only virtual camera producer.

No Gazebo truth, MAVLink, vehicle commands or SEND authority enter this process.
Position-qualified observations remain separate from pixel-only preview output.
"""
import argparse,json,signal,time
from collections import deque,Counter
from pathlib import Path
from queue import Empty
from uuid import uuid4

from vehicle_autonomy.contracts.core.geometry import Pose3
from vehicle_autonomy.world.mapping.grid import atomic_json
from vehicle_autonomy.world.sensors.camera.live import atomic
from vehicle_autonomy.world.sensors.camera.motion import match_position,MotionPending
from vehicle_autonomy.world.sensors.camera.nadir_stream import NadirStream,read_motion,capture_from_metadata
from .ultralytics_pt import PtDetector
from .rescue_geometry import project
from .landing_marker import detect_h,overlap
from .preview import annotated_packet
from .association import TargetAssociator


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);args=parser.parse_args()
    config=json.loads(args.config.read_text());root=args.config.parent;stop=False
    def finish(*_):
        nonlocal stop;stop=True
    signal.signal(signal.SIGTERM,finish);signal.signal(signal.SIGINT,finish)
    import cv2
    cv2.setNumThreads(1)
    epoch=uuid4().hex;source=NadirStream(root,config,epoch).start();settings=source.settings
    associator=TargetAssociator();faults=deque(maxlen=32);stats=Counter();previous_fault=None;last=0
    def fault(exc):
        nonlocal previous_fault
        reason=str(exc);stats['rejected']+=1;stats['reason:'+reason]+=1
        if reason!=previous_fault:
            faults.append(dict(error=reason,at_ns=time.monotonic_ns(),last_sequence=last))
            atomic_json(root/'faults.json',list(faults));previous_fault=reason
        atomic_json(root/'health.json',dict(error=reason,published_ns=time.monotonic_ns(),worker_epoch=epoch,
            reference_id=source.rectifier.reference_id,rectification_valid=False,stats=dict(stats)))
    try:
        # The producer is already serving frames while Torch/model warm up.
        detector=PtDetector(config['model_path'],config['model_sha256'],device=config['device'],
            threshold=config['confidence'],iou=config['iou'])
        while not stop:
            try:captured=source.ready.get(timeout=.05)
            except Empty:
                if source.fatal:raise RuntimeError(source.fatal)
                continue
            metadata=captured.metadata;capture=captured.capture_ns;seq=metadata['sequence']
            try:
                if not 0<=time.monotonic_ns()-capture<=500_000_000:raise ValueError('inference input expired')
                # Only localization waits for position. It cannot block the
                # producer, its view, or publication of later original frames.
                while not stop:
                    now=time.monotonic_ns();motion=read_motion(root)
                    try:
                        position,bracket=match_position(motion,capture,now,expected_key=captured.attitude.key,
                            max_distance_ns=int(settings['max_sample_distance_ms']*1e6),
                            max_span_ns=int(settings['max_bracket_span_ms']*1e6))
                        break
                    except MotionPending:time.sleep(.005)
                if stop:break
                pose=Pose3(position,captured.attitude.orientation)
                camera=captured.frame.camera.with_pose(pose)
                rectification=dict(captured.rectification,**camera.metadata(),position_valid=True,position_bracket_ns=list(bracket))
                image=captured.frame.image;began=time.monotonic_ns()
                neural=detector.detect(image);markers=detect_h(image)
                detected=[(d,'pt') for d in neural if not any(overlap(d.xyxy,m.xyxy)>.4 for m in markers)]
                detected.extend((d,'h_marker') for d in markers)
                detected=[(d,backend) for d,backend in detected if captured.frame.accepts(d.xyxy)]
                ended=time.monotonic_ns();values=[];projected=[]
                if ended-capture>1_000_000_000:raise ValueError('inference deadline exceeded')
                for detection,backend in sorted(detected,key=lambda item:-item[0].confidence):
                    label=detector.names[detection.class_id]
                    try:point=project(detection,pose,label,virtual_camera=camera)
                    except ValueError:continue
                    projected.append((point,label,backend,detection))
                identifiers=associator.update([(p,label,backend) for p,label,backend,d in projected],ended)
                for key,(point,label,backend,detection) in zip(identifiers,projected):
                    values.append(dict(id=key,label=label,position=[point.x,point.y,point.z],confidence=detection.confidence,
                        xyxy=list(detection.xyxy),detector=backend))
                atomic_json(root/'detections.json',dict(schema=2,worker_epoch=epoch,world_generation=captured.attitude.key[0],
                    camera_source=config['camera_topic'],sequence=seq,captured_ns=capture,received_ns=ended,
                    image_domain='virtual_nadir',calibration_id=settings['calibration_id'],reference_id=camera.reference_id,
                    model_sha256=config['model_sha256'],backend='ultralytics_pt',marker_backend='yellow_disc_h_shape_v1',objects=values,error=None))
                stats['processed']+=1;previous_fault=None;last=seq
                atomic_json(root/'health.json',dict(error=None,published_ns=ended,captured_ns=capture,inference_ns=ended-began,
                    object_count=len(values),backend='ultralytics_pt',worker_epoch=epoch,reference_id=camera.reference_id,
                    rectification_valid=True,stabilization=rectification,stats=dict(stats)))
                try:
                    atomic(root/'preview.packet',annotated_packet(image,metadata,detected,detector.names,epoch=epoch,
                        world_generation=captured.attitude.key[0],model_sha256=config['model_sha256'],captured_host_ns=capture,
                        started_ns=began,completed_ns=ended,rectification=rectification))
                except (OSError,ValueError,TypeError) as exc:
                    atomic_json(root/'preview-health.json',dict(error=str(exc),published_ns=time.monotonic_ns()))
            except (OSError,ValueError,KeyError,TypeError) as exc:fault(exc)
    finally:source.close()
    return 0


if __name__=='__main__':raise SystemExit(main())
