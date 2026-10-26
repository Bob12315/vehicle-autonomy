"""Real middleware denial test using only the read-only enclave credential."""
import argparse,json
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--namespace',required=True);p.add_argument('--result',type=Path,required=True);a,args=p.parse_known_args()
    import rclpy
    from rclpy.node import Node
    from rclpy.action import ActionClient
    from nav2_msgs.action import NavigateToPose
    from geometry_msgs.msg import TwistStamped
    rclpy.init(args=args);node=Node('vaf_readonly_viewer',start_parameter_services=False);out={}
    try:
        try:
            pub=node.create_publisher(TwistStamped,a.namespace+'/cmd_vel_final',10)
            msg=TwistStamped();msg.header.frame_id='base_link';msg.twist.linear.x=.1;pub.publish(msg)
            out['final_publication_denied']=False
        except Exception as exc:out.update(final_publication_denied=True,publication_error_type=type(exc).__name__)
        try:
            client=ActionClient(node,NavigateToPose,a.namespace+'/navigate_to_pose')
            out['goal_client_denied']=False
        except Exception as exc:out.update(goal_client_denied=True,goal_error_type=type(exc).__name__)
        out['passed']=out['final_publication_denied'] and out['goal_client_denied']
        a.result.write_text(json.dumps(out,indent=2))
        if not out['passed']:raise AssertionError('read-only enclave acquired a protected command/Goal endpoint')
    finally:node.destroy_node();rclpy.shutdown()
if __name__=='__main__':main()
