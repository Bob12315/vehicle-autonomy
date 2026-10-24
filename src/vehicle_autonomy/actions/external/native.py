"""Cooperative local jobs. A cancellation request is not a stopped thread."""
from threading import Event,RLock,Thread


class NativeJob:
    def __init__(self,function):
        self._cancel=Event();self._lock=RLock();self._status={'state':'RUNNING'}
        def feedback(value):
            with self._lock:
                if self._status['state']=='RUNNING':self._status={'state':'RUNNING','feedback':value}
        def run():
            try:
                value=function(self._cancel,feedback)
                state='CANCELLED' if self._cancel.is_set() else 'SUCCEEDED'
                with self._lock:self._status={'state':state,'result':value}
            except Exception as exc:
                with self._lock:self._status={'state':'FAILED','error':'local job failed: '+type(exc).__name__}
        self._thread=Thread(target=run,daemon=True);self._thread.start()
    def poll(self):
        with self._lock:return dict(self._status)
    def cancel(self):self._cancel.set()
    def close(self):self._thread.join(.1)
