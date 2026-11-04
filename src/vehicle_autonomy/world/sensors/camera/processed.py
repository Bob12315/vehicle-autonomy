"""Read-only view of an owned inference worker's atomic annotated frame.

This adapter owns no capture/inference process. Source retirement closes only
this view; the original vehicle owner keeps authoritative worker cleanup.
"""
from pathlib import Path
from threading import RLock
import time

from .packet import decode, MAX_PACKET, STALE_NS


class DetectionPreviewSource:
    def __init__(self,directory,raw_source,world_reader,health_reader,*,model_sha256,source):
        self.path=Path(directory)/'preview.packet'
        self.raw_source=raw_source;self.world_reader=world_reader;self.health_reader=health_reader
        self.model_sha256=model_sha256;self.source=source
        self.closed=False;self.epoch=None;self.lock=RLock()

    def _packet(self):
        if self.closed:raise ValueError('processed view retired')
        if not self.raw_source.health().get('online'):raise ValueError('original camera unavailable')
        health=self.health_reader()
        if not health or not health.get('worker_alive') or health.get('model_sha256')!=self.model_sha256:
            raise ValueError('YOLO inference unavailable')
        with self.path.open('rb') as stream:metadata,jpeg=decode(stream.read(MAX_PACKET+1))
        now=time.monotonic_ns();world=self.world_reader()
        if (world is None or metadata.get('world_generation')!=str(world.version.generation_id)
                or metadata.get('kind')!='yolo' or metadata.get('source')!=self.source
                or metadata.get('model_sha256')!=self.model_sha256):
            raise ValueError('processed frame source/model/World changed')
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
                return dict(kind='yolo',display_name='YOLO 识别画面',online=False,state='STALE',
                    reason=str(exc),age_ns=None,source=self.source)

    def close(self):
        with self.lock:self.closed=True
