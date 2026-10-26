"""Actual detector references -> World and original-time Mission events."""
import json
from threading import Thread,Event
import time
from pathlib import Path

from vehicle_autonomy.contracts.streams import FrameDescriptor
from vehicle_autonomy.world.model.streams import StreamProfile
from vehicle_autonomy.world.sensors.stream_store import StreamReader
from vehicle_autonomy.app.bootstrap.stream_collector import StreamCollector
from vehicle_autonomy.world.perception.vision.detection_input import validate_detection


class PerceptionCollector:
    def __init__(self,driver,directory,*,source_id,origin_id,calibration_version,events,camera_source,camera_generation,model_sha256):
        self.driver=driver;self.root=Path(directory);self.events=events;self.source_id=source_id;self.reader=None;self.registered=False;self.error=None;self.stop=Event();self.expected=dict(camera_source=camera_source,camera_generation=camera_generation,model_sha256=model_sha256)
        frames={'detections':FrameDescriptor('camera_optical','image_pixels',origin_id,units='pixels'),'preview':FrameDescriptor('camera_optical','camera_optical',origin_id)}
        self.streams=StreamCollector(driver,directory,source_id=source_id,origin_id=origin_id,calibration_version=calibration_version,frames=frames,max_age_ns=2_000_000_000)
        self.thread=Thread(target=self._run,name='perception-event-collector',daemon=True);self.thread.start()
    def _run(self):
        while not self.stop.wait(.05):
            now=self.driver.clock()
            try:
                if self.streams.input.error:raise ValueError('detector unavailable')
                world=self.driver.snapshot()
                item=next((s for s in world.streams if s.header.source_id==self.source_id and s.header.sensor_id=='detections'),None) if world else None
                if item is None:continue
                if not self.registered:
                    h=item.header;self.events.register(StreamProfile(h.source_id,h.sensor_id,h.kind,h.generation,h.frame,h.calibration_version,h.source_kind,2_000_000_000));self.registered=True
                if self.reader is None:self.reader=StreamReader(self.root/'payloads',slots=4,max_bytes=2_000_000)
                value=validate_detection(item,json.loads(self.reader.load(item.data)),**self.expected);self.events.publish_observation(item,value,now);self.error=None
            except (OSError,ValueError,KeyError,TypeError) as exc:
                self.error=type(exc).__name__+': '+str(exc)
                if self.registered:self.events.degraded(self.source_id,'detections',now,self.error)
    def close(self):
        self.stop.set();self.thread.join(2);self.streams.close()
        if self.thread.is_alive():raise RuntimeError('perception event collector still alive')
