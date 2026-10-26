"""Actual native DDS authentication/permissions probe, no vehicle IO."""
import argparse
import json
from pathlib import Path
import time


def main():
    p=argparse.ArgumentParser();p.add_argument('--role',choices=('server','allowed','viewer','unsigned'),required=True);p.add_argument('--result',type=Path,required=True);a,args=p.parse_known_args()
    import rclpy
    from rclpy.node import Node
    from rclpy.action import ActionClient,ActionServer
    from nav2_msgs.action import NavigateToPose
    from std_msgs.msg import String
    rclpy.init(args=args);n=Node('security_'+a.role,start_parameter_services=False);record={'role':a.role,'received':0,'goals_executed':0,'publisher_denied':False,'goal_completed':False,'goal_denied':False}
    def receive(m):record['received']+=1
    n.create_subscription(String,'/phase5/probe/final',receive,10)
    if a.role=='server':
        pub=n.create_publisher(String,'/phase5/probe/final',10)
        def execute(handle):
            record['goals_executed']+=1;handle.succeed();return NavigateToPose.Result()
        server=ActionServer(n,NavigateToPose,'/phase5/probe/navigate',execute_callback=execute)
        n.create_timer(.1,lambda:pub.publish(String(data='actual authenticated final producer')))
    if a.role in ('allowed','viewer'):
        if a.role=='viewer':
            try:n.create_publisher(String,'/phase5/probe/final',10)
            except Exception:record['publisher_denied']=True
        try:client=ActionClient(n,NavigateToPose,'/phase5/probe/navigate')
        except Exception:record['goal_denied']=True;client=None
        if client:
            if client.wait_for_server(timeout_sec=4):
                future=client.send_goal_async(NavigateToPose.Goal());until=time.monotonic()+4
                while not future.done() and time.monotonic()<until:rclpy.spin_once(n,timeout_sec=.05)
                if future.done() and future.result() and future.result().accepted:
                    result=future.result().get_result_async()
                    while not result.done() and time.monotonic()<until:rclpy.spin_once(n,timeout_sec=.05)
                    record['goal_completed']=result.done() and result.result().status==4
            else:record['goal_denied']=True
    until=time.monotonic()+(25 if a.role=='server' else 3)
    try:
        while time.monotonic()<until:rclpy.spin_once(n,timeout_sec=.05)
    finally:
        a.result.write_text(json.dumps(record,indent=2));n.destroy_node();rclpy.shutdown()


if __name__=='__main__':main()
