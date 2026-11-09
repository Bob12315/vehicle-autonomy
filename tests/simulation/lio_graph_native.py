"""Owned simulation-only DDS observer and deliberate TF authority conflict."""
import argparse,json,os,signal,time
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--domain',required=True,type=int)
    p.add_argument('--topics',required=True);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--conflict',action='store_true');a=p.parse_args()
    if not 1<=a.domain<=232:raise ValueError('leased simulation domain required')
    os.environ['ROS_DOMAIN_ID']=str(a.domain)
    import rclpy
    from rclpy.node import Node
    from tf2_msgs.msg import TFMessage
    topics=json.loads(a.topics);rclpy.init(args=[]);node=Node('vaf_acceptance_tf_conflict' if a.conflict else 'vaf_acceptance_graph')
    stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    if a.conflict:
        publisher=node.create_publisher(TFMessage,topics[0],10)
        publisher.publish(TFMessage())  # Authority conflict, no invented robot pose.
    deadline=time.monotonic()+4
    try:
        while not stopped and (a.conflict or time.monotonic()<deadline):
            rclpy.spin_once(node,timeout_sec=.05)
        a.output.write_text(json.dumps({topic:[dict(node=e.node_name,namespace=e.node_namespace)
            for e in node.get_publishers_info_by_topic(topic)] for topic in topics},indent=2)+'\n')
    finally:node.destroy_node();rclpy.shutdown()


if __name__=='__main__':main()
