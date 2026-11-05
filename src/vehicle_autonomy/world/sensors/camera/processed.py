"""Read-only view of an owned inference worker's atomic annotated frame.

This adapter owns no capture/inference process. Source retirement closes only
this view; the original vehicle owner keeps authoritative worker cleanup.
"""
from pathlib import Path
from threading import RLock
import time

from .packet import decode, MAX_PACKET, STALE_NS


class DetectionPreviewSource:
    def __init__(self,directory,raw_source,world_reader,health_reader,*,model_sha256,source,
                 kind='yolo',filename='preview.packet',display_name='YOLO 识别画面',image_domain=None):
        self.path=Path(directory)/filename
        self.raw_source=raw_source;self.world_reader=world_reader;self.health_reader=health_reader
        self.model_sha256=model_sha256;self.source=source
        self.kind=kind;self.display_name=display_name;self.image_domain=image_domain;self.reference_id=None
        self.closed=False;self.epoch=None;self.lock=RLock()

    def _packet(self):
        if self.closed:raise ValueError('processed view retired')
        if not self.raw_source.health().get('online'):raise ValueError('original camera unavailable')
        health=self.health_reader()
        if type(health) is not dict or not health.get('worker_alive') or health.get('model_sha256')!=self.model_sha256:
            raise ValueError('YOLO inference unavailable')
        stabilization=health.get('stabilization',{})
        if self.image_domain and (type(stabilization) is not dict or stabilization.get('valid') is not True):
            raise ValueError('增稳不可用：姿态尚未同步')
        with self.path.open('rb') as stream:metadata,jpeg=decode(stream.read(MAX_PACKET+1))
        now=time.monotonic_ns();world=self.world_reader()
        if (world is None or metadata.get('world_generation')!=str(world.version.generation_id)
                or metadata.get('kind')!=self.kind or metadata.get('source')!=self.source
                or metadata.get('model_sha256')!=self.model_sha256):
            raise ValueError('processed frame source/model/World changed')
        if self.image_domain:
            rectified=metadata.get('rectification',{})
            if type(rectified) is not dict:raise ValueError('invalid virtual camera metadata')
            reference=rectified.get('reference_id')
            if (metadata.get('image_domain')!=self.image_domain or rectified.get('valid') is not True
                    or not isinstance(reference,str) or not reference
                    or reference!=stabilization.get('reference_id')
                    or self.reference_id is not None and reference!=self.reference_id):
                raise ValueError('virtual camera reference/domain changed')
            self.reference_id=reference
        original=metadata.get('original_received_ns');capture=metadata.get('captured_host_ns')
        complete=metadata.get('inference_completed_ns');epoch=metadata.get('detector_epoch')
        if (any(type(v) is not int for v in (original,capture,complete))
                or metadata['received_ns']!=original or not 0<=now-capture<=STALE_NS
                or not capture<=original<=complete<=now or not 0<=now-original<=STALE_NS
                or not isinstance(epoch,str) or not epoch):
            raise ValueError('processed frame original capture or inference time invalid')
        if self.epoch is not None and self.epoch!=epoch:raise ValueError('processed frame inference epoch changed')
        self.epoch=epoch
        return metadata,jpeg

    def packet(self):
        with self.lock:return self._packet()

    def health(self):
        with self.lock:
            try:
                metadata,_=self._packet();age=time.monotonic_ns()-metadata['captured_host_ns']
                return dict(metadata,online=True,state='ONLINE',reason=None,age_ns=age)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                return dict(kind=self.kind,display_name=self.display_name,online=False,state='STALE',
                    reason=str(exc),age_ns=None,source=self.source)

    def close(self):
        with self.lock:self.closed=True
