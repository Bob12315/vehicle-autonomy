"""Native SLAM Toolbox map/pose -> World, graph save/reload/localization.

This is algorithm qualification, not the complete A-I physical acceptance.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import time
from uuid import uuid4

from tests.simulation.launch import ROOT,install_signal_cleanup
from tests.simulation.phase5_sensors import SensorFixture
from vehicle_autonomy.app.bootstrap.stream_collector import StreamCollector
from vehicle_autonomy.contracts.streams import FrameDescriptor
from vehicle_autonomy.world.model.stream_input import observation
from vehicle_autonomy.world.sensors.stream_store import StreamReader
from vehicle_autonomy.world.mapping.grid import OccupancyGrid,MapStore,pose_from_json
from vehicle_autonomy.world.transform.tree import rotate_vector
from vehicle_autonomy.contracts.core.geometry import Vector3,Quaternion


def ros(f,label,*args):
    p=f.owned.start_process(label,[str(ROOT/'scripts/with_ros2.sh'),'ros2',*args],transient=True)
    try:code=p.wait(timeout=25)
    finally:f.owned.stop_process(p)
    if code:raise RuntimeError(label+' failed')


def start_slam(f,label,profile):
    process=f.owned.start_process(label,[str(ROOT/'scripts/with_ros2.sh'),'/usr/bin/python3','-m','vehicle_autonomy.app.bootstrap.ros2_run','slam_toolbox',
        'localization_slam_toolbox_node' if 'localization' in profile.name else 'async_slam_toolbox_node','--ros-args','--params-file',str(profile)])
    for transition in ('configure','activate'):
        worker=f.owned.start_process(label+'-'+transition,[str(ROOT/'scripts/with_ros2.sh'),'/usr/bin/python3','-m','vehicle_autonomy.app.bootstrap.ros2_lifecycle','--node','/slam_toolbox','--transition',transition,'--result',str(f.path/(label+'-'+transition+'.json'))],transient=True)
        try:code=worker.wait(timeout=25)
        finally:f.owned.stop_process(worker)
        if code:raise RuntimeError('native '+label+' '+transition+' result unconfirmed')
    return process


def read_maps(path):
    data=json.loads((path/'state.json').read_text());reader=StreamReader(path/'payloads',slots=6,max_bytes=2_000_000)
    values={k:json.loads(reader.load(observation(raw).data)) for k,raw in data['streams'].items()}
    return data,values


def wait_native(f,path,*,after=0,timeout=35):
    last=None;until=time.monotonic()+timeout
    while time.monotonic()<until:
        f.truth()
        p=path/'state.json'
        if p.exists():
            last=json.loads(p.read_text())
            if last['error'] is None and last['shape'] and set(last['streams'])=={'map','slam_pose','map_transform'}:
                now=time.monotonic_ns();age=now-last['streams']['slam_pose']['header']['captured_at']['monotonic_ns']
                world=f.driver.snapshot().streams
                if 0<=age<=500_000_000 and last['streams']['slam_pose']['header']['captured_at']['monotonic_ns']>after and last['counts'].get('slam_pose',0)>=3 and len([v for v in world if v.header.source_id==last['source_id']])==3:
                    return read_maps(path)
        time.sleep(.1)
    raise AssertionError('native SLAM inputs unavailable: '+str(last))


def walls(grid,transform):
    q=Quaternion(*transform['rotation']);t=Vector3(*transform['translation']);o=grid.origin;qi=Quaternion(-o.orientation.x,-o.orientation.y,-o.orientation.z,o.orientation.w)
    matched=[]
    for x,y in ((3.9,0),(-3.9,0),(0,3.9),(0,-3.9)):
        p=rotate_vector(q,Vector3(x,y,0));p=rotate_vector(qi,Vector3(p.x+t.x-o.position.x,p.y+t.y-o.position.y,0))
        ix,iy=math.floor(p.x/grid.resolution_m),math.floor(p.y/grid.resolution_m)
        cells=[grid.cells[j*grid.width+i] for j in range(max(0,iy-3),min(grid.height,iy+4)) for i in range(max(0,ix-3),min(grid.width,ix+4))]
        matched.append(bool(cells and max(cells)>=65))
    if not all(matched):raise AssertionError('actual map lost scene walls: '+str(matched))
    return matched


def run(path):
    f=SensorFixture(path);collector=None;report={'passed':False,'native':'slam_toolbox 2.8.5','motion_requested':False}
    os.environ['VAF_SLAM_BOUNDARY_LIBRARY']=str((ROOT/'artifacts/phase5-world-navigation/slam-boundary/libvaf_slam_boundary.so').resolve())
    def start_reader(name):
        nonlocal collector
        root=path/name;root.mkdir(mode=0o700);c=dict(schema=1,directory=str(root),source_id='slam:'+uuid4().hex,frame_epoch=f.sensor_config['frame_epoch'],map_epoch=map_epoch,calibration_version='owned-rover-sensors-v1')
        profile=path/(name+'.json');profile.write_text(json.dumps(c))
        collector=StreamCollector(f.driver,root,source_id=c['source_id'],origin_id=c['frame_epoch'],calibration_version=c['calibration_version'],
            frames={k:FrameDescriptor('map','ENU',map_epoch) for k in ('map','slam_pose','map_transform')},max_age_ns={'map':10_000_000_000,'slam_pose':500_000_000,'map_transform':500_000_000})
        process=f.owned.start_process(name,[str(ROOT/'scripts/with_ros2.sh'),'/usr/bin/python3','-m','vehicle_autonomy.world.mapping.slam_streams','--config',str(profile)])
        return root,process
    try:
        f.start();map_epoch='map:'+uuid4().hex
        root,reader=start_reader('mapping-reader')
        slam=start_slam(f,'mapping',ROOT/'simulation/phase5/slam_mapping.yaml')
        state,values=wait_native(f,root);report['initial']=state
        grid=OccupancyGrid.from_document(values['map']);report['walls']=walls(grid,values['map_transform'])
        assert state['shape']['known']>=500 and state['shape']['occupied']>=100
        store=MapStore(path/'maps');digest=store.save(grid);store.export_pgm(digest,path/'export')
        ros(f,'save-native-graph','service','call','/slam_toolbox/serialize_map','slam_toolbox/srv/SerializePoseGraph',json.dumps({'filename':str(path/'native_map')}))
        report['saved_files']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [path/'native_map.posegraph',path/'native_map.data']}
        assert all((path/name).stat().st_size>0 for name in report['saved_files'])
        f.owned.stop_process(slam);f.owned.stop_process(reader);collector.close();collector=None
        # A new reader source/generation is admitted explicitly after native restart.
        profile=path/'slam_localization.yaml';config=(ROOT/'simulation/phase5/slam_mapping.yaml').read_text().replace('    mode: mapping','    mode: localization')
        profile.write_text(config+'    map_file_name: '+str(path/'native_map')+'\n    map_start_pose: [0.0, 0.0, 0.0]\n')
        root,reader=start_reader('localization-reader');restarted=time.monotonic_ns();slam=start_slam(f,'localization',profile)
        state,values=wait_native(f,root,after=restarted);report['localization']=state
        report['reload_walls']=walls(OccupancyGrid.from_document(values['map']),values['map_transform'])
        assert state['generation']!=report['initial']['generation']
        # Continued real stationary scans must produce new native estimates.
        before=state['counts']['slam_pose'];time.sleep(2);state,values=wait_native(f,root)
        assert state['counts']['slam_pose']>=before+5,'native localization stopped sampling'
        report['continued_pose_count']=state['counts']['slam_pose']
        f.owned.stop_process(slam)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline and any(s.header.kind.value=='slam_pose' for s in f.driver.snapshot().streams):time.sleep(.05)
        assert not any(s.header.kind.value=='slam_pose' for s in f.driver.snapshot().streams),'dead native localization still qualified'
        assert not f.writer,'read-only SLAM wrote vehicle effects'
        report.update(passed=True,writer_calls=0,map_sha256=digest)
    except BaseException as exc:
        report['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        try:
            if collector:collector.close()
            f.close()
        finally:(path/'summary.json').write_text(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args();install_signal_cleanup();print(run(a.run_dir.resolve())['passed'],flush=True)
