"""Owned, bounded attitude-only producer independent from inference/position.

The consumer gets immutable frame references through a bounded queue. Preview
and its 64-slot export ring retain original exposure facts; neither can create
World observations or write a vehicle command.
"""
from collections import Counter,deque
from dataclasses import dataclass
import json,time
from pathlib import Path
from queue import Queue,Full,Empty
from threading import Event,Thread

from .packet import decode,encode,MAX_PACKET,STALE_NS
from .live import atomic
from .motion import match_attitude,MotionPending
from .virtual_nadir import VirtualNadir,validate_config
from vehicle_autonomy.world.mapping.grid import atomic_json


def capture_from_metadata(metadata):
    if 'capture_host_lower_ns' in metadata:
        bound=metadata['capture_host_lower_ns']
        if type(bound) is not int or not 0<=bound<=metadata['received_ns']:
            raise ValueError('qualified original camera clock correlation unavailable')
        return bound
    return metadata['clock_host_ns']+metadata['captured_ns']-metadata['clock_sim_ns']


def read_motion(root):
    with (Path(root)/'pose.json').open('rb') as stream:raw=stream.read(65537)
    if len(raw)>65536:raise ValueError('camera motion history budget')
    return json.loads(raw)


@dataclass(frozen=True)
class StabilizedCapture:
    metadata: dict
    capture_ns: int
    attitude: object
    frame: object
    rectification: dict


class NadirStream:
    def __init__(self,root,config,epoch):
        self.root=Path(root);self.config=config;self.epoch=epoch
        self.settings=validate_config(config['virtual_nadir']);self.rectifier=VirtualNadir()
        self.pending=deque();self.ready=Queue(maxsize=4);self.stop=Event();self.thread=None
        self.stats=Counter();self.last_sequence=0;self.motion_key=None;self.latest=None
        self.fatal=None;self.last_reason='waiting for original camera and attitude';self.last_health=0
        self.history=self.root/'stabilized-history';self.history.mkdir(mode=0o700,exist_ok=False)

    def start(self):
        self.thread=Thread(target=self._run,name='virtual-nadir-producer',daemon=True);self.thread.start()
        return self

    def _capture(self):
        with Path(self.config['camera_packet']).open('rb') as stream:metadata,jpeg=decode(stream.read(MAX_PACKET+1))
        if metadata['source']!=self.config['camera_topic'] or metadata['capture_clock']!='gazebo-simulation':
            raise RuntimeError('owned original camera source changed')
        sequence=metadata['sequence']
        if sequence<self.last_sequence:raise RuntimeError('owned camera sequence regressed')
        if sequence==self.last_sequence:return
        self.stats['capture_sequence_gaps']+=max(0,sequence-self.last_sequence-1) if self.last_sequence else 0
        self.last_sequence=sequence;self.stats['received']+=1
        if len(self.pending)>=8:self.pending.popleft();self.stats['pending_overflow']+=1
        try:capture=capture_from_metadata(metadata)
        except ValueError:self.stats['capture_clock_rejected']+=1;raise
        self.pending.append((metadata,jpeg,capture))

    def _produce(self,metadata,jpeg,capture,attitude):
        import cv2,numpy as np
        began=time.monotonic_ns();image=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
        if image is None:raise ValueError('original camera JPEG decode failed')
        frame=self.rectifier.rectify_attitude(image,attitude)
        q=attitude.orientation
        rectification=dict(valid=True,**frame.camera.metadata(),attitude_rate_hz=attitude.attitude_rate_hz,
            attitude_bracket_ns=list(attitude.attitude_bracket_ns),body_orientation_flu_enu=[q.x,q.y,q.z,q.w],
            position_bracket_ns=None,valid_fraction=float(np.count_nonzero(frame.valid_mask)/frame.valid_mask.size),
            rectify_ms=(time.monotonic_ns()-began)/1e6,position_valid=False)
        captured=StabilizedCapture(metadata,capture,attitude,frame,rectification)
        try:self.ready.put_nowait(captured)
        except Full:
            try:self.ready.get_nowait()
            except Empty:pass
            self.stats['inference_queue_overflow']+=1;self.ready.put_nowait(captured)
        display=frame.image.copy();cv2.rectangle(display,(0,0),(639,28),(25,30,35),-1)
        cv2.putText(display,'VIRTUAL NADIR | YAW LOCKED',(8,20),cv2.FONT_HERSHEY_SIMPLEX,.5,(240,245,240),1,cv2.LINE_AA)
        ok,encoded=cv2.imencode('.jpg',display,[cv2.IMWRITE_JPEG_QUALITY,85])
        if not ok:raise ValueError('virtual camera preview encode failed')
        now=time.monotonic_ns()
        header=dict(metadata,kind='stabilized',display_name='增稳画面',original_kind=metadata['kind'],
            original_frame=metadata.get('frame'),frame='virtual_nadir_optical',spatial_calibration=rectification['calibration_id'],
            original_received_ns=metadata['received_ns'],captured_host_ns=capture,inference_started_ns=began,
            inference_completed_ns=now,processed_ns=now,model_sha256=self.config['model_sha256'],detector_epoch=self.epoch,
            world_generation=attitude.key[0],image_domain='virtual_nadir',rectification=rectification,
            detections=[],frame_role='virtual_nadir')
        packet=encode(header,encoded.tobytes());slot=self.history/format(metadata['sequence']%64,'02d')
        slot.mkdir(exist_ok=True)
        atomic(slot/'raw.packet',encode(metadata,jpeg));atomic(slot/'stabilized.packet',packet)
        atomic(self.root/'stabilized.packet',packet)
        self.latest=header;self.stats['produced']+=1;self.last_reason=None

    def step(self):
        try:self._capture()
        except (OSError,ValueError,KeyError,TypeError) as exc:self.last_reason=str(exc)
        now=time.monotonic_ns()
        if self.pending:
            try:motion=read_motion(self.root)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                self.last_reason=str(exc);motion=None
            while self.pending:
                metadata,jpeg,capture=self.pending[0];now=time.monotonic_ns()
                if not 0<=now-capture<=400_000_000:
                    self.pending.popleft();self.stats['capture_expired']+=1;continue
                if motion is None:break
                try:
                    attitude=match_attitude(motion,capture,now,expected_key=self.motion_key,
                        max_distance_ns=int(self.settings['max_sample_distance_ms']*1e6),
                        max_span_ns=int(self.settings['max_bracket_span_ms']*1e6),
                        min_attitude_rate_hz=self.settings['min_attitude_rate_hz'])
                    self.motion_key=attitude.key
                except MotionPending:
                    self.stats['attitude_wait_polls']+=1;break
                except (ValueError,KeyError,TypeError) as exc:
                    self.pending.popleft();self.stats['attitude_rejected']+=1
                    self.stats['reason:'+str(exc)]+=1;self.last_reason=str(exc);continue
                self.pending.popleft()
                try:self._produce(metadata,jpeg,capture,attitude)
                except (OSError,ValueError,TypeError) as exc:
                    self.stats['render_or_export_error']+=1;self.last_reason=str(exc)
        now=time.monotonic_ns()
        if now-self.last_health>=50_000_000:
            latest=self.latest
            valid=self.fatal is None and latest is not None and 0<=now-latest['captured_host_ns']<=STALE_NS
            atomic_json(self.root/'stabilization-health.json',dict(published_ns=now,rectification_valid=valid,
                error=None if valid else self.fatal or self.last_reason or 'original capture stale',worker_epoch=self.epoch,
                reference_id=self.rectifier.reference_id,captured_ns=None if latest is None else latest['captured_host_ns'],
                stabilization=dict({} if latest is None else latest['rectification'],valid=valid,stats=dict(self.stats),pending=len(self.pending))))
            self.last_health=now

    def _run(self):
        try:
            while not self.stop.is_set():self.step();self.stop.wait(.005)
        except Exception as exc:
            self.fatal=type(exc).__name__+': '+str(exc)
            atomic_json(self.root/'stabilization-health.json',dict(published_ns=time.monotonic_ns(),
                rectification_valid=False,error=self.fatal,worker_epoch=self.epoch,reference_id=self.rectifier.reference_id))

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(3)
            if self.thread.is_alive():raise RuntimeError('virtual camera producer shutdown unconfirmed')
