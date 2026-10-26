"""Filesystem/JSON work never runs on the MAVLink/Safety owner thread."""
from threading import Thread,Event
import time
from vehicle_autonomy.world.model.stream_input import WorkerStreamInput


class StreamCollector:
    def __init__(self,driver,directory,*,source_id,origin_id,calibration_version,frames,max_age_ns=500_000_000):
        self.driver=driver;self.port=driver.stream_ingress();self.input=WorkerStreamInput(self.port,directory,
            source_id=source_id,origin_id=origin_id,calibration_version=calibration_version,frames=frames,max_age_ns=max_age_ns)
        self.stop=Event();self.cycles=0;self.max_poll_ns=0
        self.thread=Thread(target=self._run,name='world-stream-collector',daemon=True);self.thread.start()
    def _run(self):
        while not self.stop.wait(.05):
            if self.driver.stream_ingress().generation_id!=self.port.generation_id:
                self.port.withdraw_streams(self.input.source_id);self.input.error='vehicle world epoch changed; fresh source admission required';return
            start=time.monotonic_ns();self.input.poll(self.driver.clock());self.cycles+=1
            self.max_poll_ns=max(self.max_poll_ns,time.monotonic_ns()-start)
    def close(self):
        self.stop.set();self.thread.join(2);self.port.withdraw_streams(self.input.source_id)
        if self.thread.is_alive():raise RuntimeError('stream collector still alive; no new source may be admitted')
