"""Filesystem/JSON work never runs on the MAVLink/Safety owner thread."""
from threading import Thread,Event
from collections import deque
import math
import time
from vehicle_autonomy.world.model.stream_input import WorkerStreamInput


class StreamCollector:
    def __init__(self,driver,directory,*,source_id,origin_id,calibration_version,frames,max_age_ns=500_000_000,poll_period_s=.05):
        if type(poll_period_s) not in (int,float) or not math.isfinite(poll_period_s) or not .01<=poll_period_s<=.1:raise ValueError('bounded collector poll interval required')
        self.poll_period_s=poll_period_s
        self.driver=driver;self.port=driver.stream_ingress();self.input=WorkerStreamInput(self.port,directory,
            source_id=source_id,origin_id=origin_id,calibration_version=calibration_version,frames=frames,max_age_ns=max_age_ns)
        self.errors=deque(maxlen=128);self.rejected_polls=0;self._last_error=None;self.stop=Event();self.cycles=0;self.max_poll_ns=0
        self.thread=Thread(target=self._run,name='world-stream-collector',daemon=True);self.thread.start()
    def _run(self):
        try:
            while not self.stop.wait(self.poll_period_s):
                if self.driver.stream_ingress().generation_id!=self.port.generation_id:
                    self.input.error='vehicle world epoch changed; fresh source admission required';return
                start=time.monotonic_ns();self.input.poll(self.driver.clock(),clock=self.driver.clock);self.cycles+=1
                if self.input.error:
                    self.rejected_polls+=1
                    if self.input.error!=self._last_error:self.errors.append(dict(at_ns=time.monotonic_ns(),error=self.input.error))
                self._last_error=self.input.error
                self.max_poll_ns=max(self.max_poll_ns,time.monotonic_ns()-start)
        except Exception as exc:
            self.input.error='collector stopped: '+type(exc).__name__
            self.errors.append(dict(at_ns=time.monotonic_ns(),error=self.input.error))
        finally:self.port.withdraw_streams(self.input.source_id)
    def close(self):
        self.stop.set();self.thread.join(2);self.port.withdraw_streams(self.input.source_id)
        if self.thread.is_alive():raise RuntimeError('stream collector still alive; no new source may be admitted')
