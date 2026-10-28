"""Actual ROS subscriptions and RViz subscriber evidence, not a PID-only Ready."""
import argparse
import json
from pathlib import Path
import time

from .config import frames,load,vehicle_context
from .state import MAX_AGE_S


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=('bridge-health','bridge-ready','rviz-health','rviz-ready'));p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    config=load(a.config);ctx=vehicle_context();names=frames(ctx,config)
    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.qos import QoSProfile,ReliabilityPolicy
    from nav_msgs.msg import Odometry
    from std_msgs.msg import String
    from tf2_msgs.msg import TFMessage
    rclpy.init(args=[]);node=Node('vaf_visualization_probe',namespace=names['namespace'] or '/',parameter_overrides=[Parameter('use_sim_time',value=config.get('use_sim_time',False))])
    samples=set();transforms=set();status=[];qos=QoSProfile(depth=10,reliability=ReliabilityPolicy.BEST_EFFORT)
    def stamp(s):return s.sec*1_000_000_000+s.nanosec
    def odometry(m):
        if m.header.frame_id==names['odom'] and m.child_frame_id==names['base']:samples.add(stamp(m.header.stamp))
    def tf(m):
        for t in m.transforms:
            if t.header.frame_id==names['odom'] and t.child_frame_id==names['base']:transforms.add(stamp(t.header.stamp))
    def health(m):
        try:
            s=json.loads(m.data)
            if s['vehicle_id']==ctx['vehicle_id'] and s['vehicle_type']==ctx['vehicle_type']:status.append(s)
        except (ValueError,KeyError,TypeError):pass
    try:
        if a.operation.endswith('ready'):
            node.create_subscription(Odometry,names['topic']+'/odometry',odometry,qos)
            node.create_subscription(TFMessage,names['tf'],tf,qos)
            node.create_subscription(String,names['topic']+'/status',health,qos)
        end=time.monotonic()+(1.6 if a.operation.endswith('ready') else .55)
        while time.monotonic()<end:rclpy.spin_once(node,timeout_sec=.05)
        expected='vaf_rviz' if a.operation.startswith('rviz') else 'vaf_visualization_bridge'
        nodes=set(node.get_node_names_and_namespaces());present=(expected,names['namespace'] or '/') in nodes
        ready=present;now=node.get_clock().now().nanoseconds
        if a.operation.endswith('ready'):
            # Idle native telemetry can be 1 Hz. Require a new sample during
            # this active probe, never just retained graph/status metadata.
            recent=lambda values:any(0<=now-t<=int((MAX_AGE_S+.2)*1e9) for t in values)
            ready=bool(present and status and status[-1]['valid'] and 0<=now-int(status[-1]['stamp_ns'])<=800_000_000 and recent(samples) and recent(transforms))
            if a.operation=='rviz-ready':
                for topic in ('markers','trajectory'):
                    ready=ready and any(e.node_name=='vaf_rviz' and e.node_namespace==(names['namespace'] or '/') for e in node.get_subscriptions_info_by_topic(names['topic']+'/'+topic))
        value=dict(status='READY' if ready else 'WAITING',vehicle=ctx['vehicle_id'],operation=a.operation,node_present=present,odom_samples=len(samples),tf_samples=len(transforms),
            bridge=None if not status else status[-1],vehicle_authority=False)
        print(json.dumps(value,allow_nan=False),flush=True);return 0 if ready else 2
    finally:node.destroy_node();rclpy.shutdown()


if __name__=='__main__':raise SystemExit(main())
