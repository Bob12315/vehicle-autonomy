"""Actual authenticated graph/TF readiness diagnostics; no Goal or vehicle I/O."""
import argparse,json,time
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--result',type=Path,required=True);a,args=p.parse_known_args()
    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from sensor_msgs.msg import LaserScan
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from nav_msgs.msg import OccupancyGrid
    from tf2_ros import Buffer,TransformListener
    rclpy.init(args=args);node=Node('vaf_graph_probe',start_parameter_services=False,parameter_overrides=[Parameter('use_sim_time',value=True)])
    from rclpy.qos import qos_profile_sensor_data
    buffer=Buffer();listener=TransformListener(buffer,node);counts={k:0 for k in ('scan','map','pose')}
    def received(k,_):counts[k]+=1
    for cls,topic,key in ((LaserScan,'/scan','scan'),(OccupancyGrid,'/map','map'),(PoseWithCovarianceStamped,'/pose','pose')):node.create_subscription(cls,topic,lambda m,k=key:received(k,m),qos_profile_sensor_data)
    until=time.monotonic()+6
    while time.monotonic()<until:rclpy.spin_once(node,timeout_sec=.02)
    a.result.write_text(json.dumps(dict(counts=counts,frames=buffer.all_frames_as_yaml(),nodes=node.get_node_names_and_namespaces(),publishers={topic:[dict(node=p.node_name,ns=p.node_namespace,gid=bytes(p.endpoint_gid).hex()) for p in node.get_publishers_info_by_topic(topic)] for topic in ('/scan','/map','/pose','/tf','/tf_static')}),indent=2))
    node.destroy_node();rclpy.shutdown()
if __name__=='__main__':main()
