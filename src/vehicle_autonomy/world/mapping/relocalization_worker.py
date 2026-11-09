"""Guarded I/O around pinned FAST_LIO_LOCALIZATION2/Open3D registration.

The upstream crop, coarse/fine ICP calls, fitness gate and voxel operations are
reused unchanged. No truth input, vehicle port or competing TF broadcaster.
"""
import argparse,hashlib,importlib.util,json,signal,time
from collections import OrderedDict
from pathlib import Path
import math


def run(cfg,directory):
    import numpy as np
    import open3d as o3d
    if o3d.__version__!='0.19.0':raise ValueError('relocalization requires locked Open3D 0.19.0')
    from scipy.spatial.transform import Rotation
    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import PointCloud2
    from sensor_msgs_py import point_cloud2
    from nav_msgs.msg import Odometry
    from geometry_msgs.msg import PoseStamped,TransformStamped
    from std_msgs.msg import Header
    from rosgraph_msgs.msg import Clock
    from vehicle_autonomy.world.mapping.cloud_maps import read_pcd
    from vehicle_autonomy.world.mapping.clock import RosClockBridge
    from vehicle_autonomy.world.sensors.simulation_time import SimulationGenerationClock
    from vehicle_autonomy.world.localization.lio_input import at
    from vehicle_autonomy.world.sensors.camera.live import atomic
    module_path=Path(cfg['algorithm_module']['path'])
    if module_path.resolve()!=module_path or not module_path.is_file() or hashlib.sha256(module_path.read_bytes()).hexdigest()!=cfg['algorithm_module']['sha256']:
        raise ValueError('application-admitted relocalization module changed')
    spec=importlib.util.spec_from_file_location('pinned_fast_lio_localization',module_path)
    upstream=importlib.util.module_from_spec(spec);spec.loader.exec_module(upstream)
    data=(directory/'map.pcd').read_bytes()
    if hashlib.sha256(data).hexdigest()!=cfg['map']['sha256']:raise ValueError('relocalization map checksum changed')
    map_points=read_pcd(data);clock=RosClockBridge();source=cfg['source'];sensor=cfg['sensor']
    generation_clock=SimulationGenerationClock(sensor['world']) if source=='live' else None
    state=dict(schema=1,generation=cfg['generation'],frame_id=cfg['map']['frame_id'],revision=0,online=False,
        error='awaiting exact capture-stamped LIO scan/odometry',map_id=cfg['map']['id'],
        algorithm='FAST_LIO_LOCALIZATION2 / Open3D point-to-point ICP',initial_seed=cfg['seed'],
        seed_origin='explicit operator rough map-to-LIO transform; never Gazebo truth',localization=None)
    pending={'cloud':OrderedDict(),'odom':OrderedDict()};pins={};fault=None;stopped=False
    prefix=sensor['namespace']+'/slam';last_processed=-1;last_attempt=0.;last_write=0.;last_graph=0.
    rclpy.init(args=[])

    class Guarded(upstream.FastLIOLocalization):
        def __init__(self):
            Node.__init__(self,'vaf_relocalization',namespace=prefix+'/relocation',parameter_overrides=[Parameter('use_sim_time',value=True)])
            self.declare_parameters(namespace='',parameters=[('scan_voxel_size',.1),('map_voxel_size',.4),
                ('localization_threshold',.8),('fov',6.28319),('fov_far',40.)])
            self.global_map=o3d.geometry.PointCloud();self.global_map.points=o3d.utility.Vector3dVector(map_points[:,:3])
            self.global_map=self.voxel_down_sample(self.global_map,.4)
            self.pub_submap=self.create_publisher(PointCloud2,prefix+'/relocation/submap',10)
            self.pub_map_to_odom=self.create_publisher(TransformStamped,prefix+'/relocation/map_to_odom',10)
            self.T_map_to_odom=np.eye(4);self.T_map_to_odom[:3,3]=cfg['seed'][:3]
            self.T_map_to_odom[:3,:3]=Rotation.from_euler('z',cfg['seed'][3]).as_matrix()
            self.initialized=True;self.cur_scan=None;self.cur_odom=None;self.capture_host=None
        def pose_to_mat(self,pose):
            result=np.eye(4);q=pose.orientation;p=pose.position
            result[:3,:3]=Rotation.from_quat([q.x,q.y,q.z,q.w]).as_matrix();result[:3,3]=[p.x,p.y,p.z]
            return result
        def publish_point_cloud(self,publisher,header,pc):
            header.frame_id=cfg['map']['frame_id']
            publisher.publish(point_cloud2.create_cloud_xyz32(header,np.asarray(pc[:,:3],dtype=np.float32)))
        def publish_odom(self,transform):
            # Called by unchanged upstream fitness gate only on a real match.
            state['match_transform']=transform.tolist()
            result=TransformStamped();result.header.stamp=self.cur_odom.header.stamp;result.header.frame_id=cfg['map']['frame_id']
            result.child_frame_id=cfg['local_odom_frame']
            p=transform[:3,3];q=Rotation.from_matrix(transform[:3,:3]).as_quat()
            state['map_to_local_odom']=dict(position=p.tolist(),quaternion=q.tolist(),
                capture_ros_ns=ns(self.cur_odom.header.stamp))
            result.transform.translation.x,result.transform.translation.y,result.transform.translation.z=map(float,p)
            result.transform.rotation.x,result.transform.rotation.y,result.transform.rotation.z,result.transform.rotation.w=map(float,q)
            self.pub_map_to_odom.publish(result)

    node=Guarded()
    def ns(stamp):return stamp.sec*1_000_000_000+stamp.nanosec
    def observe(message):
        nonlocal fault
        if clock.observe(ns(message.clock),time.monotonic_ns()):fault='replay clock epoch changed'
    def receive(key):
        def cb(message):
            stamp=ns(message.header.stamp)
            if stamp<=last_processed:return
            pending[key][stamp]=(message,time.monotonic_ns())
            while len(pending[key])>20:pending[key].popitem(last=False)
        return cb
    node.create_subscription(Clock,'/clock',observe,20)
    def admitted_pose(message):
        odometry=Odometry();odometry.header=message.header;odometry.pose.pose=message.pose
        receive('odom')(odometry)
    node.create_subscription(PoseStamped,prefix+'/admitted_pose',admitted_pose,20)
    node.create_subscription(PointCloud2,prefix+'/registered',receive('cloud'),qos_profile_sensor_data)
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        while not stopped:
            rclpy.spin_once(node,timeout_sec=.005);now=time.monotonic_ns();error=fault
            try:
                if now/1e9-last_graph>=.25:
                    for topic,name in ((prefix+'/admitted_pose','vaf_lio_adapter'),(prefix+'/registered','vaf_lio_adapter'),('/clock','vaf_mid360' if source=='live' else 'rosbag2_player')):
                        entries=node.get_publishers_info_by_topic(topic)
                        if len(entries)!=1 or entries[0].node_name!=name:raise LookupError('unqualified input publisher: '+topic)
                        gid=bytes(entries[0].endpoint_gid).hex()
                        if topic in pins and pins[topic]!=gid:fault='relocalization input publisher restarted'
                        pins[topic]=gid
                    last_graph=now/1e9
                if fault:raise ValueError(fault)
                ready=pending['cloud'].keys() & pending['odom'].keys()
                if ready and now/1e9-last_attempt>=.25:
                    stamp=max(ready);cloud,cr=pending['cloud'][stamp];odom,ore=pending['odom'][stamp];received=min(cr,ore)
                    if generation_clock:capture=generation_clock.lower_bound(stamp,at(now),strict_previous=True).monotonic_ns
                    else:
                        earlier=[h for s,h in clock.pairs if 0<=stamp-s<=100_000_000 and h<=received]
                        if not earlier:raise LookupError('waiting for replay clock correlation')
                        capture=max(earlier)
                    if capture>received or now-capture>1_000_000_000:raise LookupError('registration input stale/future')
                    values=point_cloud2.read_points_numpy(cloud,field_names=('x','y','z'),skip_nans=True)
                    if not 2000<=len(values)<=200000:raise ValueError('registration scan budget/geometry')
                    node.cur_scan=o3d.geometry.PointCloud();node.cur_scan.points=o3d.utility.Vector3dVector(values)
                    node.cur_odom=odom;state.pop('match_transform',None)
                    began=time.monotonic_ns();node.global_localization(node.T_map_to_odom)
                    ended=time.monotonic_ns();fitness=node.last_registration_result.fitness
                    state.update(fitness=fitness,inlier_rmse_m=node.last_registration_result.inlier_rmse,
                        registration_host_ms=(ended-began)/1e6,capture_ros_ns=stamp,
                        registration_input_age_host_ms=(began-capture)/1e6,
                        registration_completion_age_host_ms=(ended-capture)/1e6)
                    if 'match_transform' in state and ended-capture<=1_000_000_000:
                        body=node.pose_to_mat(odom.pose.pose)
                        # Input pose is already the admitted normalized body
                        # origin. Do not apply the IMU lever arm twice.
                        pose=node.T_map_to_odom@body;q=Rotation.from_matrix(pose[:3,:3]).as_quat()
                        state['revision']+=1;state['localization']=dict(capture_ros_ns=stamp,captured_host_ns=capture,
                            published_host_ns=ended,position=pose[:3,3].tolist(),quaternion=q.tolist(),derived_twist=None)
                    else:
                        state['localization']=None;error='registration fitness rejected' if fitness<=.8 else 'registration completed after freshness deadline'
                        state['last_registration_rejection']=dict(reason=error,capture_ros_ns=stamp,
                            fitness=fitness,registration_host_ms=(ended-began)/1e6,
                            completion_age_host_ms=(ended-capture)/1e6)
                    last_processed=stamp;last_attempt=ended/1e9
                    for q in pending.values():
                        for value in list(q):
                            if value<=stamp:del q[value]
                pose=state['localization']
                if pose is None or time.monotonic_ns()-pose['captured_host_ns']>1_000_000_000:raise LookupError(error or 'no fresh qualified registration')
            except LookupError as exc:error=str(exc)
            except ValueError as exc:
                if generation_clock and not generation_clock.fault:error=str(exc)
                else:fault=str(exc);error=fault
            now=time.monotonic_ns();state.update(online=error is None,error=error,published_host_ns=now,publishers=pins)
            if now/1e9-last_write>.1:atomic(directory/'state.json',json.dumps(state,allow_nan=False).encode());last_write=now/1e9
    finally:
        state.update(online=False,error=fault or 'relocalization stopped',published_host_ns=time.monotonic_ns())
        atomic(directory/'state.json',json.dumps(state,allow_nan=False).encode())
        if generation_clock:generation_clock.close()
        node.destroy_node();rclpy.shutdown()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);a=parser.parse_args()
    run(json.loads(a.config.read_text()),a.config.parent)


if __name__=='__main__':main()
