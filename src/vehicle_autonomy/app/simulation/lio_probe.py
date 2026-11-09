"""Application readiness: real received map/TF at capture time and owned window."""
import argparse,json,os,time,signal
from pathlib import Path
from collections import deque


def transform_ready(cfg,frame,stamp,can_transform):
    if 'sensor' not in cfg:
        target=cfg['frame_id']
        return frame in (target,target+'/pcd_snapshot') and can_transform(target,frame,stamp)
    frames=cfg['frames'];target=frames['map']
    return (frame in (target,frames['odom']) and can_transform(target,frame,stamp)
        and can_transform(target,frames['lidar'],stamp))


def observe(cfg,output=None):
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile,DurabilityPolicy,ReliabilityPolicy,qos_profile_sensor_data
    from sensor_msgs.msg import PointCloud2
    from tf2_msgs.msg import TFMessage
    from tf2_ros import Buffer
    from rclpy.time import Time
    rclpy.init(args=[]);node=Node('vaf_lio_probe');buffer=Buffer();cloud=None;map_count=0;cloud_received=0;stopped=False;last_write=0.;cloud_headers=deque(maxlen=20)
    retained=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE)
    loaded='sensor' not in cfg;prefix=cfg['namespace'] if loaded else cfg['sensor']['namespace']+'/slam'
    def points(m):
        nonlocal cloud,cloud_received
        if m.width:
            cloud=m;cloud_received=time.monotonic_ns();cloud_headers.append((m.header.stamp,m.header.frame_id,cloud_received))
    def map_message(m):
        nonlocal map_count
        map_count=m.width
    def tf(m,static=False):
        for t in m.transforms:
            if static:buffer.set_transform_static(t,'vaf_lio_adapter')
            else:buffer.set_transform(t,'vaf_lio_adapter')
    node.create_subscription(PointCloud2,prefix+('/loaded_map' if loaded else '/'+cfg.get('registered_channel','registered')),points,retained if loaded else qos_profile_sensor_data)
    if not loaded:
        node.create_subscription(PointCloud2,prefix+'/map',map_message,retained)
        node.create_subscription(TFMessage,prefix+'/tf',tf,20)
    node.create_subscription(TFMessage,prefix+'/tf_static',lambda m:tf(m,True),retained)
    ready=False;deadline=time.monotonic()+5
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    try:
        while not stopped and (output or time.monotonic()<deadline):
            rclpy.spin_once(node,timeout_sec=.005)
            valid=next(((stamp,frame) for stamp,frame,received in reversed(cloud_headers) if time.monotonic_ns()-received<=1_000_000_000 and
                (loaded or map_count>0) and transform_ready(cfg,frame,Time.from_msg(stamp),buffer.can_transform)),None)
            ready=valid is not None
            result=dict(status='READY' if ready else 'WAITING',map_points=map_count,
                points=cloud.width if cloud else 0,tf_at_capture=ready if not loaded else None,loaded_map_only=loaded,
                transform_capture_ros_ns=valid[0].sec*1_000_000_000+valid[0].nanosec if valid else None,
                cloud_frame=valid[1] if valid else None,registered_channel=cfg.get('registered_channel','registered'),
                received_ns=time.monotonic_ns(),source_config_sha256=__import__('hashlib').sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest())
            if output and time.monotonic()-last_write>.1:
                from vehicle_autonomy.world.sensors.camera.live import atomic
                atomic(output,json.dumps(result).encode());last_write=time.monotonic()
            if not output and ready:break
        return result
    finally:
        if output:
            from vehicle_autonomy.world.sensors.camera.live import atomic
            atomic(output,json.dumps(dict(status='STOPPED',received_ns=time.monotonic_ns())).encode())
        node.destroy_node();rclpy.shutdown()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path);parser.add_argument('--health',type=Path)
    parser.add_argument('--output',type=Path);parser.add_argument('--window',action='store_true');a=parser.parse_args()
    if a.health:
        try:
            value=json.loads(a.health.read_text())
            if not 0<=time.monotonic_ns()-value['received_ns']<=1_000_000_000:value['status']='WAITING'
        except (OSError,ValueError,KeyError,TypeError):value=dict(status='WAITING')
    else:value=observe(json.loads(a.config.read_text()),a.output)
    if a.window:
        from vehicle_autonomy.app.control_center.desktop import windows,owned_processes
        value['windows']=windows(owned_processes(os.environ.get('VAF_TOOL_OWNERSHIP')))
        if not value['windows']:value['status']='WAITING'
    print(json.dumps(value));return 0 if value['status']=='READY' else 1


if __name__=='__main__':raise SystemExit(main())
