"""Read-only worker/window/data readiness probes; never equate a PID with data."""
import argparse
import json
import os
from pathlib import Path
import time

from .mid360_data import fresh


def health(path):
    try:
        value = json.loads(Path(path).read_text())
        return bool(isinstance(value,dict) and value.get('online') is True
                    and fresh(value.get('received_ns'), time.monotonic_ns()))
    except (OSError, ValueError, TypeError):
        return False


def observe(config, timeout=5.):
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy, ReliabilityPolicy
    from sensor_msgs.msg import PointCloud2, Imu
    from rosgraph_msgs.msg import Clock
    from tf2_msgs.msg import TFMessage
    from tf2_ros import Buffer
    from rclpy.time import Time
    from rclpy.duration import Duration
    ns = config['namespace']
    rclpy.init(args=[])
    node = Node('vaf_mid360_readiness', namespace=ns)
    counts = dict(points=0, imu=0, clock=0, tf=0, tf_static=0)
    buffer = Buffer()
    cloud = None
    def points(m):
        nonlocal cloud
        if m.width and m.header.frame_id == config['lidar_frame']:
            counts['points'] += 1
            cloud = m
    def frames(m, static=False):
        for t in m.transforms:
            if static:
                buffer.set_transform_static(t, 'gazebo_simulation')
            else:
                buffer.set_transform(t, 'gazebo_simulation')
        counts['tf_static' if static else 'tf'] += len(m.transforms)
    def count(key):
        def callback(_):
            counts[key] += 1
        return callback
    retained = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)
    node.create_subscription(PointCloud2, ns+'/points', points, qos_profile_sensor_data)
    node.create_subscription(Imu, ns+'/imu', count('imu'), qos_profile_sensor_data)
    node.create_subscription(Clock, '/clock', count('clock'), 10)
    node.create_subscription(TFMessage, ns+'/tf', frames, 10)
    node.create_subscription(TFMessage, ns+'/tf_static', lambda m: frames(m, True), retained)
    end = time.monotonic()+timeout
    ready = False
    try:
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=.05)
            if all(counts.values()) and cloud is not None:
                when = Time.from_msg(cloud.header.stamp)
                ready = buffer.can_transform(config['world_frame'], config['lidar_frame'], when, timeout=Duration(seconds=0))
                if ready:
                    break
        return dict(status='READY' if ready else 'WAITING', counts=counts, transform_at_cloud_stamp=ready,
            ros_domain_id=os.environ.get('ROS_DOMAIN_ID','0'),
            point_publishers=len(node.get_publishers_info_by_topic(ns+'/points')))
    finally:
        node.destroy_node()
        rclpy.shutdown()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--health', type=Path)
    p.add_argument('--config', type=Path)
    p.add_argument('--window', action='store_true')
    p.add_argument('--timeout',type=float,default=5.)
    a = p.parse_args()
    if a.health:
        value = dict(status='READY' if health(a.health) else 'WAITING')
    else:
        value = observe(json.loads(a.config.read_text()),timeout=max(.1,min(a.timeout,15.)))
    if a.window:
        from vehicle_autonomy.app.control_center.desktop import windows, owned_processes
        value['windows'] = windows(owned_processes(os.environ.get('VAF_TOOL_OWNERSHIP')))
        if not value['windows']:
            value['status'] = 'WAITING'
    print(json.dumps(value))
    return 0 if value['status'] == 'READY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
