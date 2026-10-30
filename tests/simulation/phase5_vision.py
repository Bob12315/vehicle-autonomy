"""Real Gazebo camera rendered photo board -> actual pinned YOLOX CPU.

The board is a rendered photograph, not a 3-D bus or a world-position estimate.
"""
import argparse
import hashlib
import json
from pathlib import Path
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment
import time
import xml.etree.ElementTree as ET

from tests.simulation.launch import ROOT,install_signal_cleanup
from tests.simulation.phase5_sensors import SensorFixture
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.world.model.stream_input import observation
from vehicle_autonomy.world.sensors.stream_store import StreamReader
from vehicle_autonomy.world.perception.vision.yolox import YoloXDetector

WEIGHTS_SHA='c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063'
PHOTO_SHA='c02019c4979c191eb739ddd944445ef408dad5679acab6fd520ef9d434bfbc63'


def board(owned):
    photo=HostEnvironment(ROOT).path('vision_assets')/'bus.jpg';assert hashlib.sha256(photo.read_bytes()).hexdigest()==PHOTO_SHA
    tree=ET.parse(owned.world_path)
    if tree.find("world/plugin[@name='gz::sim::systems::UserCommands']") is None:tree.find('world').append(ET.fromstring('<plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>'))
    tree.find('world').append(ET.fromstring(f'''<model name="vision_photo_board"><static>true</static><pose>2 0 .65 0 0 0</pose><link name="board">
      <collision name="board_collision"><geometry><box><size>.04 .9 1.2</size></box></geometry></collision>
      <visual name="rendered_photo"><pose>0 0 0 1.57079632679 0 0</pose><geometry><plane><normal>-1 0 0</normal><size>.9 1.2</size></plane></geometry>
      <material><lighting>false</lighting><diffuse>1 1 1 1</diffuse><ambient>1 1 1 1</ambient><pbr><metal><albedo_map>{photo.as_uri()}</albedo_map><metalness>0</metalness><roughness>1</roughness></metal></pbr></material></visual>
    </link></model>'''));tree.find('world').append(ET.fromstring('''<light name="vision_fill" type="directional"><direction>1 0 -.1</direction><diffuse>1 1 1 1</diffuse><specular>0 0 0 1</specular></light>'''));tree.write(owned.world_path)


def image(root):
    import numpy as np
    import cv2
    state=json.loads((root/'state.json').read_text());item=observation(state['streams']['camera']);h,w,_=item.data.dimensions
    raw=StreamReader(root/'payloads').load(item.data);rgb=np.frombuffer(raw,dtype=np.uint8).reshape(h,w,3)
    bgr=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR) if item.data.media_type=='application/x-raw-rgb8' else rgb.copy()
    return item,bgr


def run(path):
    f=SensorFixture(path);board(f.owned);report={'passed':False,'motion_requested':False,'scene':'Gazebo rendered photo board; image-only detections, no 3-D bus claim'}
    try:
        f.start();until=time.monotonic()+30
        while time.monotonic()<until:
            f.truth()
            try:item,bgr=image(path/'streams');break
            except (ValueError,KeyError,OSError):time.sleep(.1)
        else:raise AssertionError('real camera sample missing')
        import cv2
        cv2.imwrite(str(path/'actual-gazebo-camera.png'),bgr)
        detector=YoloXDetector(HostEnvironment(ROOT).path('vision_assets')/'yolox.onnx',WEIGHTS_SHA)
        start=time.monotonic_ns();detections=detector.detect(bgr);latency=time.monotonic_ns()-start
        report.update(input_header=to_json_value(item.header),detections=[dict(class_id=d.class_id,confidence=d.confidence,xyxy=d.xyxy) for d in detections],inference_ns=latency,backend='opencv_dnn_cpu',opencv=cv2.__version__,model_sha256=WEIGHTS_SHA)
        for d in detections:
            x0,y0,x1,y1=(int(v) for v in d.xyxy);cv2.rectangle(bgr,(x0,y0),(x1,y1),(0,255,0),2)
        cv2.imwrite(str(path/'actual-inference.png'),bgr)
        assert any(d.class_id==5 for d in detections),'pinned actual YOLO did not detect bus in actual Gazebo image'
        assert not f.writer,'vision qualification wrote vehicle effects'
        report.update(passed=True,writer_calls=0)
    except BaseException as exc:report['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        try:f.close()
        finally:(path/'summary.json').write_text(json.dumps(report,indent=2))
    return report


def run_stream(path):
    import os
    import signal
    import sys
    from uuid import uuid4
    from vehicle_autonomy.world.model.stream_events import ObservationEvents
    from vehicle_autonomy.app.bootstrap.perception_collector import PerceptionCollector
    events=ObservationEvents();f=SensorFixture(path,events=events);board(f.owned);collector=None
    report={'passed':False,'motion_requested':False,'mode':'actual Gazebo -> real YOLO process -> World -> original Mission runtime'}
    try:
        f.start();until=time.monotonic()+30
        while time.monotonic()<until:
            try:item,bgr=image(path/'streams');camera_state=json.loads((path/'streams/state.json').read_text());break
            except (KeyError,ValueError,OSError):f.truth();time.sleep(.1)
        else:raise AssertionError('camera never available')
        root=path/'perception';root.mkdir(mode=0o700);source='yolox:'+uuid4().hex
        config=dict(schema=1,directory=str(root),camera_directory=str(path/'streams'),camera_source=f.sensor_config['source_id'],camera_generation=camera_state['generation'],source_id=source,frame_epoch=f.sensor_config['frame_epoch'],calibration_version=f.sensor_config['calibration_version'],model_path=str(HostEnvironment(ROOT).path('vision_assets')/'yolox.onnx'),model_sha256=WEIGHTS_SHA)
        (path/'perception-profile.json').write_text(json.dumps(config,indent=2))
        collector=PerceptionCollector(f.driver,root,source_id=source,origin_id=config['frame_epoch'],calibration_version=config['calibration_version'],events=events,camera_source=config['camera_source'],camera_generation=config['camera_generation'],model_sha256=WEIGHTS_SHA)
        def mission(identifier):
            spec=dict(schema_version=1,id=identifier,name=identifier,version='1.0.0',target='rover',root='event',timeout_s=30,nodes=[
                dict(id='event',type='Event',event='object.detected',children=['sequence']),
                dict(id='sequence',type='Sequence',children=['actual-bus','query']),
                dict(id='actual-bus',type='Condition',expression=dict(op='eq',source='blackboard',path='event.primary_label',value='bus',max_age_s=2)),
                dict(id='query',type='Action',action='GetVehicleState',parameters={})])
            return f.api('/api/missions/start',dict(spec=spec,allow_send=False))
        first=mission('yolo-real-event')
        worker=f.owned.start_process('yolo-process',[sys.executable,'-m','vehicle_autonomy.world.perception.vision.stream_worker','--config',str(path/'perception-profile.json')])
        report['mission']=f.wait_mission(first['id'],timeout=35)
        state=json.loads((root/'state.json').read_text());reader=StreamReader(root/'payloads',slots=4,max_bytes=2_000_000)
        reference=observation(state['streams']['detections']);body=json.loads(reader.load(reference.data));report['actual']=body;report['performance']=state['performance']
        assert any(d['class_id']==5 for d in body['detections']) and body['world_positions_available'] is False
        assert any(v.header.kind.value=='image_detections' for v in f.driver.snapshot().streams)
        assert not f.driver.snapshot().objects,'pixel boxes were fabricated into spatial objects'
        (path/'actual-worker-preview.jpg').write_bytes(reader.load(observation(state['streams']['preview']).data))
        # Freeze only the inference process. Vehicle/session/World owner must
        # continue and stale result metadata must not renew old image evidence.
        os.kill(worker.pid,signal.SIGSTOP)
        try:
            until=time.monotonic()+4
            while time.monotonic()<until and any(v.header.source_id==source for v in f.driver.snapshot().streams):f.truth();time.sleep(.05)
            assert not any(v.header.source_id==source for v in f.driver.snapshot().streams),'stalled inference remained qualified'
            assert f.driver.info()['connected'] and f.driver.snapshot().vehicle.health.quality.value=='VALID'
            report['inference_stall_isolated']=True
        finally:os.kill(worker.pid,signal.SIGCONT)
        second=mission('yolo-real-event-after-stall');report['recovery_mission']=f.wait_mission(second['id'],timeout=35)
        # Move the owned image board, never the vehicle, through a real Gazebo service.
        command=['gz','service','-s','/world/'+f.owned.world+'/set_pose','--reqtype','gz.msgs.Pose','--reptype','gz.msgs.Boolean','--timeout','2000','--req','name: "vision_photo_board", position: {x: 20, y: 0, z: .65}']
        cursor=events.cursor
        move=f.owned.start_process('hide-photo-board',command,transient=True)
        try:assert move.wait(timeout=5)==0
        finally:f.owned.stop_process(move)
        assert 'data: true' in (path/'hide-photo-board.log').read_text(),'Gazebo pose service did not confirm the actual scene change'
        until=time.monotonic()+12
        while time.monotonic()<until:
            f.truth();lost=events.read(cursor,'object.lost',f.lab.clock())
            if lost:break
            time.sleep(.1)
        else:raise AssertionError('actual no-detection frames did not produce object.lost')
        state=json.loads((root/'state.json').read_text());body=json.loads(reader.load(observation(state['streams']['detections']).data))
        assert body['detected'] is False and not body['detections'],'hidden board still produced detection'
        report.update(passed=True,no_detection=body,event_frames=events.accepted_frames,event_cursor=events.cursor,writer_calls=len(f.writer))
        assert not f.writer,'perception/Query Mission wrote vehicle commands'
    except BaseException as exc:report['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        if collector:
            report['collector_status']=dict(error=collector.error,input_error=collector.streams.input.error,cycles=collector.streams.cycles)
            report['world_kinds_before_cleanup']=[v.header.kind.value for v in f.driver.snapshot().streams] if f.driver.snapshot() else []
        try:
            if collector:collector.close()
            f.close()
        finally:(path/'summary.json').write_text(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--stream',action='store_true');a=p.parse_args();install_signal_cleanup();print((run_stream if a.stream else run)(a.run_dir.resolve())['passed'],flush=True)
