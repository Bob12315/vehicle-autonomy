"""Bounded, ROS-free map accumulation child of the owned LIO process group.

Only already admitted capture-stamped arrays cross its bounded IPC queues.
No pose estimator, clock invention, TF publisher or vehicle channel lives here.
"""
from dataclasses import asdict
from pathlib import Path
from queue import Empty,Full
import os,signal,time

from .cloud_maps import VoxelMap,pcd_bytes
from vehicle_autonomy.world.sensors.stream_store import StreamStore


def accumulate(config,directory,inputs,outputs,stopping):
    directory=Path(directory);cloud_map=VoxelMap(**config['map_limits'])
    store=StreamStore(directory/'payloads',slots=4)
    exported=0.;last_source=0;last_host=0;retained=0;exported_revision=-1;last_heartbeat=0.
    state=dict(map_worker=dict(pid=os.getpid(),generation=config['generation']))
    def stop(*_):stopping.set()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def send(payload=None):
        state['map_worker']['heartbeat_host_ns']=time.monotonic_ns()
        packet=(dict(state),payload)
        try:outputs.put_nowait(packet)
        except Full:
            try:outputs.get_nowait()
            except Empty:pass
            try:outputs.put_nowait(packet)
            except Full:pass
    try:
        while not stopping.is_set():
            payload=None
            try:
                source,captured_host,values=inputs.get(timeout=.1)
                if source<=last_source and not cloud_map.paused:raise ValueError('admitted map capture regressed')
                previous=cloud_map.revision;cloud_map.paused=(directory/'pause').exists();cloud_map.update(values)
                if cloud_map.revision!=previous:last_source,last_host=source,captured_host
                if time.monotonic()-exported>=1 and cloud_map.cells and exported_revision!=cloud_map.revision:
                    points=cloud_map.points()
                    if len(points):
                        retained=len(points);reference=asdict(store.put(pcd_bytes(points),'application/vnd.pcd',channel='map3d'))
                        state.update(map_reference=reference,map_export_capture_ros_ns=last_source,
                            map_export_capture_host_ns=last_host,map_export_revision=cloud_map.revision)
                        payload=(last_source,retained,points.astype('<f4').tobytes())
                        exported=time.monotonic();exported_revision=cloud_map.revision
            except Empty:pass
            state['map']=dict(points=retained,candidate_voxels=len(cloud_map.cells),revision=cloud_map.revision,
                min_observations=cloud_map.min_observations,paused=cloud_map.paused,error=cloud_map.error,capture_ros_ns=last_source)
            if payload is not None or time.monotonic()-last_heartbeat>=.1:
                send(payload);last_heartbeat=time.monotonic()
    except Exception as exc:
        state['map']=dict(points=retained,error='map worker: '+str(exc));send()
        raise
    finally:
        # The owning process-group supervisor handles abrupt parent loss.
        # Never block child exit on an offline consumer's full result queue.
        outputs.cancel_join_thread();outputs.close();inputs.close()
