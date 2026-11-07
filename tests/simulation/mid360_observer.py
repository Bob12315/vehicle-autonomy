"""Read-only native ROS evidence collector. No publications or vehicle port."""
import argparse,json,math,signal,time
from pathlib import Path


def run(config,output):
    import numpy as np,rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.qos import qos_profile_sensor_data,QoSProfile,DurabilityPolicy,ReliabilityPolicy
    from rclpy.time import Time
    from sensor_msgs.msg import PointCloud2,Imu,LaserScan
    from rosgraph_msgs.msg import Clock
    from tf2_msgs.msg import TFMessage
    from tf2_ros import Buffer
    from nav_msgs.msg import Path as RosPath
    from std_msgs.msg import String
    from vehicle_autonomy.world.sensors.camera.live import atomic
    rclpy.init(args=[]);node=Node('mid360_acceptance_observer',parameter_overrides=[Parameter('use_sim_time',value=True)])
    stopped=False
    def stop(*_):
        nonlocal stopped;stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    ns=config['namespace'];buffer=Buffer();last_cloud=None;checked=None;first_position=None;started=time.monotonic_ns()
    state=dict(counts={k:0 for k in ('points','imu','tf','tf_static','clock','description','path','status')},
        empty_clouds=0,empty_paths=0,valid_cloud_tf_cuts=0,invalid=[],max_displacement_m=0.,max_path=0,
        max_wall_hits=0,max_world_z=None,min_world_z=None,static_edges=[],pose_samples=[],clock_regressions=0)
    dtype=np.dtype(dict(names=['x','y','z','intensity','range','ring','time','offset','timestamp'],
        formats=['<f4']*5+['<u2','<f4','<u4','<f8'],offsets=[0,4,8,12,16,20,24,28,32],itemsize=40))
    def ns_stamp(s):return s.sec*1_000_000_000+s.nanosec
    def cloud(m):
        nonlocal last_cloud
        if not m.width:state['empty_clouds']+=1;return
        state['counts']['points']+=1;last_cloud=m
        state['last_cloud_ns']=ns_stamp(m.header.stamp);state['last_cloud_received_ns']=time.monotonic_ns()
    def imu(m):
        state['counts']['imu']+=1
        a=m.linear_acceleration;w=m.angular_velocity
        state['imu']=dict(frame=m.header.frame_id,stamp_ns=ns_stamp(m.header.stamp),
            acceleration=[a.x,a.y,a.z],angular_velocity=[w.x,w.y,w.z],acceleration_norm=math.sqrt(a.x*a.x+a.y*a.y+a.z*a.z),
            orientation_covariance=list(m.orientation_covariance))
        if not all(math.isfinite(v) for v in (a.x,a.y,a.z,w.x,w.y,w.z)):state['invalid'].append('nonfinite IMU')
    def frames(m,static=False):
        state['counts']['tf_static' if static else 'tf']+=len(m.transforms)
        for t in m.transforms:
            if static:
                buffer.set_transform_static(t,'native_mid360_observer')
                edge=[t.header.frame_id,t.child_frame_id]
                if edge not in state['static_edges']:state['static_edges'].append(edge)
                if t.header.frame_id==config['world_frame']:state['invalid'].append('static world transform')
            else:buffer.set_transform(t,'native_mid360_observer')
    def clock(m):
        stamp=ns_stamp(m.clock)
        if stamp<state.get('clock_ns',0):state['clock_regressions']+=1
        state['clock_ns']=stamp;state['counts']['clock']+=1
    def description(m):
        state['counts']['description']+=1
        state['robot_description']=m.data
    def path(m):
        state['counts']['path']+=1;state['max_path']=max(state['max_path'],len(m.poses))
        if not m.poses:state['empty_paths']+=1
    def status(m):
        state['counts']['status']+=1
        try:state['status']=json.loads(m.data)
        except ValueError:state['invalid'].append('invalid source status')
    def scan(m):
        state['counts']['rs16_scan']=state['counts'].get('rs16_scan',0)+1
        state['rs16_scan']=dict(frame=m.header.frame_id,bins=len(m.ranges),stamp_ns=ns_stamp(m.header.stamp),
            finite_bins=sum(math.isfinite(v) for v in m.ranges))
    retained=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE)
    for kind,topic,callback,qos in ((PointCloud2,ns+'/points',cloud,qos_profile_sensor_data),
        (Imu,ns+'/imu',imu,qos_profile_sensor_data),(Clock,'/clock',clock,10),
        (TFMessage,ns+'/tf',frames,100),(TFMessage,ns+'/tf_static',lambda m:frames(m,True),retained),
        (String,ns+'/robot_description',description,retained),(RosPath,ns+'/trajectory',path,10),
        (String,ns+'/status',status,10),(LaserScan,'/vaf/lidar/scan',scan,qos_profile_sensor_data)):
        node.create_subscription(kind,topic,callback,qos)
    def inspect(m):
        nonlocal first_position
        stamp=ns_stamp(m.header.stamp)
        if m.header.frame_id!=config['lidar_frame'] or m.point_step!=40 or len(m.data)!=m.width*40:
            raise ValueError('cloud layout/frame')
        values=np.frombuffer(bytes(m.data),dtype=dtype)
        if not all(np.isfinite(values[k]).all() for k in ('x','y','z','intensity','range','timestamp')):
            raise ValueError('nonfinite cloud')
        if not (np.all(values['time']==0) and np.all(values['offset']==0) and np.all(values['timestamp']==float(stamp))):
            raise ValueError('invented per-point time or changed capture stamp')
        if not (np.all(values['ring']<28) and np.all(values['range']>=.099) and np.all(values['range']<=40.1)):
            raise ValueError('cloud range/ring')
        when=Time.from_msg(m.header.stamp)
        t=buffer.lookup_transform(config['world_frame'],config['lidar_frame'],when).transform
        body=buffer.lookup_transform(config['world_frame'],config['model_frame'],when).transform
        mount=buffer.lookup_transform(config['base_frame'],config['lidar_frame'],when).transform
        expected=config['mount'][:3]
        if any(abs(v-e)>1e-7 for v,e in zip((mount.translation.x,mount.translation.y,mount.translation.z),expected)):
            raise ValueError('sensor mount translation')
        q=t.rotation;x,y,z,w=q.x,q.y,q.z,q.w
        rotation=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
            [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
            [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
        xyz=np.stack([values[k] for k in ('x','y','z')],axis=1)@rotation.T
        xyz+=np.array([t.translation.x,t.translation.y,t.translation.z])
        wall=(abs(xyz[:,0]-11.85)<.08)&(abs(xyz[:,1])<11.5)&(xyz[:,2]>.1)&(xyz[:,2]<5.9)
        state['max_wall_hits']=max(state['max_wall_hits'],int(wall.sum()))
        state['max_world_z']=max(float(xyz[:,2].max()),state['max_world_z'] or -float('inf'))
        state['min_world_z']=min(float(xyz[:,2].min()),state['min_world_z'] or float('inf'))
        position=[body.translation.x,body.translation.y,body.translation.z]
        if first_position is None:first_position=position
        state['max_displacement_m']=max(state['max_displacement_m'],math.dist(position,first_position))
        state['valid_cloud_tf_cuts']+=1
        state['last_transform']=dict(stamp_ns=stamp,position=position,lidar_translation=[t.translation.x,t.translation.y,t.translation.z])
        state['pose_samples']=(state['pose_samples']+[dict(stamp_ns=stamp,position=position)])[-100:]
    published=0.
    try:
        while not stopped:
            rclpy.spin_once(node,timeout_sec=.01)
            if last_cloud is not None and checked!=ns_stamp(last_cloud.header.stamp):
                try:inspect(last_cloud)
                except (ValueError,TypeError) as exc:state['invalid']=(state['invalid']+[str(exc)])[-20:]
                except Exception:pass  # TF may arrive after this sensor exposure; retry the same cut.
                else:checked=ns_stamp(last_cloud.header.stamp)
            if time.monotonic()-published>.5:
                published=time.monotonic();state['observed_host_ns']=time.monotonic_ns()
                state['duration_s']=(state['observed_host_ns']-started)/1e9
                state['clock_publishers']=len(node.get_publishers_info_by_topic('/clock'))
                state['point_publishers']=len(node.get_publishers_info_by_topic(ns+'/points'))
                atomic(output,json.dumps(state).encode())
    finally:
        atomic(output,json.dumps(state).encode());node.destroy_node();rclpy.shutdown()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    run(json.loads(a.config.read_text()),a.output)
