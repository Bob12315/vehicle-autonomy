"""Actual ROS topic/TF observer. --propose publishes an explicitly synthetic
standard PoseStamped candidate, never a vehicle command or Nav2 action."""
import argparse,json,math,signal,time
from pathlib import Path
from vehicle_autonomy.world.mapping.grid import atomic_json


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--namespace',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--propose',nargs=3,type=float);a=p.parse_args()
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile,ReliabilityPolicy
    from nav_msgs.msg import Odometry,Path as RosPath
    from geometry_msgs.msg import PoseStamped
    from sensor_msgs.msg import NavSatFix
    from std_msgs.msg import String
    from tf2_msgs.msg import TFMessage
    from visualization_msgs.msg import MarkerArray
    rclpy.init(args=[]);node=Node('vaf_acceptance_observer');ns=a.namespace.rstrip('/')+'/viz';stop=False
    def stopping(*_):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGTERM,stopping);signal.signal(signal.SIGINT,stopping)
    report=dict(source='actual ROS subscriptions; no vehicle writes',counts={},first=None,last=None,max_path=0,stale_seen=False,tf_publishers=0,status=None)
    stream=a.output.with_suffix('.jsonl').open('w');qos=QoSProfile(depth=20,reliability=ReliabilityPolicy.BEST_EFFORT)
    def count(key):report['counts'][key]=report['counts'].get(key,0)+1
    def odom(m):
        count('odom');v=dict(host_ns=time.monotonic_ns(),stamp_ns=m.header.stamp.sec*1_000_000_000+m.header.stamp.nanosec,frame=m.header.frame_id,child=m.child_frame_id,
            position=[m.pose.pose.position.x,m.pose.pose.position.y,m.pose.pose.position.z],orientation=[m.pose.pose.orientation.x,m.pose.pose.orientation.y,m.pose.pose.orientation.z,m.pose.pose.orientation.w],
            body_velocity=[m.twist.twist.linear.x,m.twist.twist.linear.y,m.twist.twist.linear.z])
        if report['first'] is None:report['first']=v
        report['last']=v;stream.write(json.dumps(v)+'\n');stream.flush()
    def path(m):count('path');report['path_length']=len(m.poses);report['max_path']=max(report['max_path'],len(m.poses));report['empty_path_seen']=report.get('empty_path_seen',False) or not m.poses
    def tf(m):
        count('tf');report['tf_edges']=list({(t.header.frame_id,t.child_frame_id) for t in m.transforms});report['tf_publishers']=node.count_publishers(ns+'/tf')
    def status(m):
        count('status');value=json.loads(m.data);report['status']=value
        if not value['valid']:report['stale_seen']=True
    def gps(m):count('gps');report['gps']=dict(fix=m.status.status,altitude=None if not math.isfinite(m.altitude) else m.altitude,covariance_type=m.position_covariance_type)
    def markers(m):count('markers');report['delete_seen']=report.get('delete_seen',False) or any(v.action==3 for v in m.markers)
    for cls,topic,callback in ((Odometry,'odometry',odom),(RosPath,'trajectory',path),(TFMessage,'tf',tf),(String,'status',status),(NavSatFix,'gps/fix',gps),(MarkerArray,'markers',markers)):
        node.create_subscription(cls,ns+'/'+topic,callback,qos)
    publisher=node.create_publisher(PoseStamped,ns+'/pending_goal',10) if a.propose else None;sent=False;last=0
    try:
        while rclpy.ok() and not stop:
            rclpy.spin_once(node,timeout_sec=.05)
            if a.propose and not sent and report['status'] and report['status']['valid'] and publisher.get_subscription_count()>0:
                m=PoseStamped();m.header.frame_id=report['status']['frames']['odom'];m.header.stamp=node.get_clock().now().to_msg();m.pose.position.x,m.pose.position.y,m.pose.position.z=a.propose;m.pose.orientation.w=1.;publisher.publish(m);sent=True;report['synthetic_proposal_published']=True
            if time.monotonic()-last>.2:atomic_json(a.output,report);last=time.monotonic()
    finally:
        atomic_json(a.output,report);stream.close();node.destroy_node();rclpy.shutdown()


if __name__=='__main__':main()
