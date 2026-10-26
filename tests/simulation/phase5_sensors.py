"""Real Gazebo camera/2D+3D LiDAR/IMU and signed AP -> ROS data only.

Does not use Gazebo truth as a localization input or send vehicle effects.
"""
import argparse
import json
import os
from pathlib import Path
import time
import xml.etree.ElementTree as ET

from tests.simulation.launch import ROOT,install_signal_cleanup
from tests.simulation.mission_fixture import MissionFixture
from tests.simulation.ros2_mapping import add_mapping_scene


def sensors(owned):
    add_mapping_scene(owned,room_yaw=0.)
    tree=ET.parse(owned.model_path);link=tree.find('model/link[@name="base_link"]')
    link.append(ET.fromstring('''<sensor name="rgb_camera" type="camera"><pose>.15 0 .25 0 0 0</pose>
      <always_on>true</always_on><update_rate>10</update_rate><topic>/phase5/gz/camera</topic>
      <camera><horizontal_fov>1.25</horizontal_fov><image><width>640</width><height>480</height><format>R8G8B8</format></image><clip><near>.05</near><far>20</far></clip></camera></sensor>'''))
    link.append(ET.fromstring('''<sensor name="lidar3d" type="gpu_lidar"><pose>0 0 .25 0 0 0</pose>
      <always_on>true</always_on><update_rate>5</update_rate><topic>/phase5/gz/lidar3d</topic>
      <lidar><scan><horizontal><samples>360</samples><resolution>1</resolution><min_angle>-3.14159265</min_angle><max_angle>3.14159265</max_angle></horizontal>
      <vertical><samples>16</samples><resolution>1</resolution><min_angle>-.261799</min_angle><max_angle>.261799</max_angle></vertical></scan><range><min>.2</min><max>12</max><resolution>.01</resolution></range></lidar></sensor>'''))
    tree.write(owned.model_path)


def bridge_config(path,world):
    topics=[('/clock',f'/world/{world}/clock','rosgraph_msgs/msg/Clock','gz.msgs.Clock'),
        ('/phase5/camera/image_raw','/phase5/gz/camera','sensor_msgs/msg/Image','gz.msgs.Image'),
        ('/phase5/camera/info','/phase5/gz/camera_info','sensor_msgs/msg/CameraInfo','gz.msgs.CameraInfo'),
        ('/phase5/scan_raw','/vaf/lidar','sensor_msgs/msg/LaserScan','gz.msgs.LaserScan'),
        ('/phase5/points','/phase5/gz/lidar3d/points','sensor_msgs/msg/PointCloud2','gz.msgs.PointCloudPacked'),
        ('/phase5/imu',f'/world/{world}/model/target_rover/link/base_link/sensor/imu_sensor/imu','sensor_msgs/msg/Imu','gz.msgs.IMU')]
    # JSON is a valid YAML document and keeps topic types exact and reviewable.
    path.write_text(json.dumps([dict(ros_topic_name=r,gz_topic_name=g,ros_type_name=rt,gz_type_name=gt,direction='GZ_TO_ROS',qos_profile='SENSOR_DATA') for r,g,rt,gt in topics],indent=2))


class SensorFixture(MissionFixture):
    def __init__(self,path,source_time_sync=False,secure=False,**kwargs):
        super().__init__(path,'rover',driver_options={'source_time_sync':source_time_sync,'cycle_period_ns':20_000_000 if source_time_sync else None},**kwargs);self.collector=None;self.source_time_sync=source_time_sync;self.secure=secure;self.security_environment={}
        sensors(self.owned)
        from tests.simulation.phase5_setup import telemetry_rates
        original_start=self.owned.start
        def start_owned():
            original_start();telemetry_rates(self.owned,hz=20 if source_time_sync else 10)
            if source_time_sync:self.owned.verify_parameters({'SERIAL0_BAUD':115.},'phase5_clock_uart_baud')
        self.owned.start=start_owned
    def ros_start(self,name,command,role,**kwargs):
        if self.secure:
            command=list(command)
            if '--ros-args' in command:
                i=command.index('--ros-args');command[i+1:i+1]=['--enclave','/vaf/'+role]
            else:command+=['--ros-args','--enclave','/vaf/'+role]
        return self.owned.start_process(name,command,environment=self.security_environment,**kwargs)
    def start(self):
        os.environ['PYTHONPATH']=str(ROOT/'src')+os.pathsep+os.environ.get('PYTHONPATH','')
        os.environ['ROS_DOMAIN_ID']=str(120+os.getpid()%80)
        super().start();f=self;path=self.path
        if self.secure:
            from vehicle_autonomy.app.bootstrap.navigation_security import profiles
            auth=f.owned.credentials.create_state('_phase5_dds');f.owned._save()
            (path/'dds-profiles.json').write_text(json.dumps(profiles('/nav2_wire'),indent=2))
            helper=f.owned.start_process('dds-provision',[str(ROOT/'scripts/with_ros2.sh'),'/usr/bin/python3','-m','vehicle_autonomy.app.bootstrap.ros2_security','--root',str(auth/'keystore'),'--profiles',str(path/'dds-profiles.json'),'--result',str(path/'dds-provision.json')],transient=True)
            try:code=helper.wait(timeout=45)
            finally:f.owned.stop_process(helper)
            if code:raise RuntimeError('native DDS credential provisioning failed')
            self.security_environment=dict(ROS_SECURITY_ENABLE='true',ROS_SECURITY_STRATEGY='Enforce',ROS_SECURITY_KEYSTORE=str(auth/'keystore'),RMW_IMPLEMENTATION='rmw_fastrtps_cpp')
        fd=os.open(path/'stream-api.private',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            os.write(fd,f.token.encode());f.owned.credentials.register_private('stream-api.private',fd)
        finally:os.close(fd)
        f.owned._save()
        bridge_config(path/'sensor-bridge.yaml',f.owned.world)
        f.ros_start('ros-sensor-bridge',[str(ROOT/'scripts/with_ros2.sh'),'/usr/bin/python3','-m','vehicle_autonomy.app.bootstrap.ros2_run','ros_gz_bridge','parameter_bridge','--ros-args','-p','config_file:='+str(path/'sensor-bridge.yaml')],role='bridge')
        raw={'camera':[f.owned.model+'/base_link/rgb_camera'],'scan':[f.owned.model+'/base_link/mapping_lidar'],
             'cloud':[f.owned.model+'/base_link/lidar3d'],'imu':[f.owned.model+'/base_link/imu_sensor']}
        config=dict(schema=1,base_url=f.base,target='rover',token_file=str(path/'stream-api.private'),directory=str(path/'streams'),source_id='gazebo:'+f.owned.world,frame_epoch=f.driver.snapshot().version.generation_id,calibration_version='owned-rover-sensors-v1',raw_frames=raw)
        if self.source_time_sync:config['generation_clock_world']=f.owned.world
        (path/'stream-profile.json').write_text(json.dumps(config,indent=2)+'\n')
        from vehicle_autonomy.app.bootstrap.stream_collector import StreamCollector
        from vehicle_autonomy.contracts.streams import FrameDescriptor
        (path/'streams').mkdir(mode=0o700)
        frames={name:FrameDescriptor(frame,convention,config['frame_epoch']) for name,frame,convention in
            [('camera','camera_optical','camera_optical'),('scan','laser','FLU'),('cloud','lidar3d','FLU'),('imu','imu_frd','FRD')]}
        self.collector=StreamCollector(f.driver,path/'streams',source_id=config['source_id'],origin_id=config['frame_epoch'],calibration_version=config['calibration_version'],frames=frames)
        f.ros_start('world-streams',[str(ROOT/'scripts/with_ros2.sh'),'/usr/bin/python3','-m','vehicle_autonomy.world.sensors.ros2_streams','--config',str(path/'stream-profile.json')],role='sensors')
        self.sensor_config=config
        return self
    def close(self):
        try:
            if self.collector:self.collector.close()
        finally:super().close()


def run(path):
    f=SensorFixture(path);result={'passed':False,'motion_requested':False,'source':'real Gazebo RGB/2D+3D LiDAR/IMU and authenticated AP EKF; no truth localization'}
    try:
        f.start()
        deadline=time.monotonic()+35;latest=None
        while time.monotonic()<deadline:
            f.truth();file=path/'streams/state.json'
            if file.exists():
                latest=json.loads(file.read_text())
                if not latest['error'] and latest['intrinsics'] is not None and len(f.driver.snapshot().streams)==4 and all(latest['counts'].get(k,0)>=3 for k in ('camera','scan','cloud','imu','odom')):break
            time.sleep(.1)
        else:raise AssertionError('real sensor streams incomplete: '+str(latest))
        result['streams']=latest
        result['world_streams']=f.api('/api/world/vehicle?target=rover')['world']['streams']
        result['collector']=dict(cycles=f.collector.cycles,max_poll_ns=f.collector.max_poll_ns,error=f.collector.input.error)
        assert not f.writer and not f.lab.runtime.views(),'data sidecar wrote vehicle commands'
        result.update(passed=True,writer_calls=0,domain=int(os.environ['ROS_DOMAIN_ID']))
        (path/'observed-streams.json').write_text(json.dumps(latest,indent=2)+'\n')
    except BaseException as exc:
        result['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        try:
            f.close()
        finally:(path/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args();install_signal_cleanup();print(run(a.run_dir.resolve())['passed'],flush=True)
