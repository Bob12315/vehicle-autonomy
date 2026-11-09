"""Owned rosbag player with separate current replay provenance, never live status."""
import argparse
import json
from pathlib import Path
import signal
import subprocess
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--bag', type=Path, required=True)
    p.add_argument('--qos', type=Path, required=True)
    p.add_argument('--once', action='store_true')
    a = p.parse_args()
    config = json.loads(a.config.read_text())
    ns = config['namespace']
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import PointCloud2, Imu
    from rosgraph_msgs.msg import Clock
    from std_msgs.msg import String
    rclpy.init(args=[])
    node = Node('vaf_mid360_replay_source', namespace=ns)
    status = node.create_publisher(String, ns+'/status', 10)
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    last = {}
    counts = dict(points=0, imu=0, clock=0)
    def receive(key):
        def callback(message):
            if key == 'points' and not message.width:
                return
            last[key] = time.monotonic_ns()
            counts[key] += 1
        return callback
    node.create_subscription(PointCloud2,ns+'/points',receive('points'),qos_profile_sensor_data)
    node.create_subscription(Imu,ns+'/imu',receive('imu'),qos_profile_sensor_data)
    node.create_subscription(Clock,'/clock',receive('clock'),10)
    # Same owned process group: the Tool supervisor reaps the CLI and any ROS
    # descendants even if this wrapper crashes. No daemon or ROS CLI discovery.
    process = subprocess.Popen(['ros2','bag','play',str(a.bag),*([] if a.once else ['--loop']),
        '--qos-profile-overrides-path',str(a.qos),'--remap',ns+'/status:='+ns+'/recorded_status'])
    try:
        last_status = 0.
        while not stopped and process.poll() is None:
            rclpy.spin_once(node, timeout_sec=.05)
            if time.monotonic()-last_status > .25:
                last_status = time.monotonic()
                now = time.monotonic_ns()
                online = all(k in last and 0 <= now-last[k] < 1_000_000_000 for k in counts)
                status.publish(String(data=json.dumps(dict(source='rosbag2', bag_id=a.bag.name,
                    online=online, counts=counts, received_ns=now, live_simulation=False))))
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        node.destroy_node()
        rclpy.shutdown()
    return 0 if stopped else process.returncode


if __name__ == '__main__':
    raise SystemExit(main())
