"""Explicit read-only recording of original/processed camera pairs.

Records evidence to an explicitly supplied export directory. It owns only its
observer thread and files, never a camera, inference worker or vehicle port.
Encoding/rendering is deliberately outside the running simulation owner.
"""
from collections import OrderedDict
import json
from pathlib import Path
from threading import Event,Lock,Thread
import time


def same_capture(original,processed):
    return (all(type(original.get(key)) is int and original[key]>=0 for key in ('sequence','captured_ns','received_ns'))
        and isinstance(original.get('source'),str) and bool(original['source'])
        and original.get('capture_clock')=='gazebo-simulation'
        and processed.get('sequence')==original.get('sequence')
        and processed.get('source')==original.get('source')
        and processed.get('captured_ns')==original.get('captured_ns')
        and processed.get('capture_clock')==original.get('capture_clock')
        and processed.get('original_received_ns')==original.get('received_ns')
        and processed.get('image_domain')=='virtual_nadir'
        and processed.get('kind')=='stabilized'
        and type(processed.get('rectification')) is dict
        and processed['rectification'].get('valid') is True)


class CameraComparisonRecorder:
    def __init__(self,directory,original,processed,*,binding,max_frames=20000):
        self.directory=Path(directory);self.directory.mkdir(mode=0o700,parents=True,exist_ok=False)
        (self.directory/'raw').mkdir();(self.directory/'stabilized').mkdir()
        self.original=original;self.processed=processed;self.binding=dict(binding);self.max_frames=max_frames
        self.stop=Event();self.lock=Lock();self.phase={'mission_state':'PREPARING','action':None,'completed':0}
        self.events=[];self.started_ns=time.monotonic_ns();self.error=None;self.closed=False
        self.raw_count=0;self.paired_count=0;self.unpaired_count=0;self.cache=OrderedDict()
        self.last_raw=-1;self.last_processed=-1
        self.raw_log=(self.directory/'raw.jsonl').open('w')
        self.processed_log=(self.directory/'stabilized.jsonl').open('w')
        self.thread=Thread(target=self._run,name='camera-comparison-observer',daemon=True);self.thread.start()

    def update_phase(self,mission_state,actions):
        current=next((a for a in reversed(actions) if a['state'] in ('RUNNING','CANCELLING')),None)
        phase=dict(mission_state=mission_state,action=None if current is None else current['name'],
            parameters={} if current is None else current.get('parameters',{}),
            completed=sum(a['state']=='SUCCEEDED' for a in actions))
        with self.lock:
            if phase!=self.phase:
                self.phase=phase;self.events.append(dict(at_ns=time.monotonic_ns(),**phase))

    def _run(self):
        try:
            while not self.stop.is_set():
                try:metadata,jpeg=self.original.packet()
                except (OSError,ValueError):pass
                else:
                    seq=metadata['sequence']
                    if seq<self.last_raw:raise ValueError('recorded original camera sequence regressed')
                    if seq>self.last_raw:
                        if self.raw_count>=self.max_frames:raise ValueError('explicit camera recording frame budget exceeded')
                        if metadata.get('capture_clock')!='gazebo-simulation':raise ValueError('explicit simulation capture clock required')
                        with self.lock:phase=dict(self.phase)
                        filename='raw/'+str(seq).zfill(9)+'.jpg'
                        (self.directory/filename).write_bytes(jpeg)
                        row=dict(observed_ns=time.monotonic_ns(),filename=filename,metadata=metadata,phase=phase)
                        self.raw_log.write(json.dumps(row,separators=(',',':'))+'\n');self.raw_log.flush()
                        self.cache[seq]=metadata
                        while len(self.cache)>64:self.cache.popitem(last=False)
                        self.raw_count+=1;self.last_raw=seq
                try:metadata,jpeg=self.processed.packet()
                except (OSError,ValueError):pass
                else:
                    seq=metadata['sequence']
                    if seq>self.last_processed:
                        original=self.cache.get(seq)
                        if original is not None and same_capture(original,metadata):
                            filename='stabilized/'+str(seq).zfill(9)+'.jpg'
                            (self.directory/filename).write_bytes(jpeg)
                            row=dict(observed_ns=time.monotonic_ns(),filename=filename,metadata=metadata)
                            self.processed_log.write(json.dumps(row,separators=(',',':'))+'\n');self.processed_log.flush()
                            self.paired_count+=1;self.last_processed=seq
                        elif original is not None:
                            raise ValueError('processed camera does not match the recorded original exposure')
                        elif seq<self.last_raw:self.unpaired_count+=1;self.last_processed=seq
                self.stop.wait(.01)
        except Exception as exc:
            self.error=type(exc).__name__+': '+str(exc)

    def close(self):
        if self.closed:return
        self.stop.set();self.thread.join(5)
        if self.thread.is_alive():raise RuntimeError('camera recording observer shutdown unconfirmed')
        self.raw_log.close();self.processed_log.close();self.closed=True
        report=dict(schema=1,binding=self.binding,started_ns=self.started_ns,ended_ns=time.monotonic_ns(),
            raw_frames=self.raw_count,paired_frames=self.paired_count,unpaired_processed_frames=self.unpaired_count,
            error=self.error,events=self.events,comparison='same-flight same-exposure original versus actual virtual-nadir output',
            missing_processed_policy='explicit unavailable panel; no old transform or image is substituted')
        (self.directory/'recording.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        if self.error:raise RuntimeError(self.error)
        return report
