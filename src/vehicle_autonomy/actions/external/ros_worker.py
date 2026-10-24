"""Explicit ROS 2 worker for the isolated Wait Action / Trigger Service contract.

No ROS imports occur in the application process. Wait is a ROS message type;
using it makes no claim that Nav2 navigation or algorithms are implemented.
"""
import argparse
import json
import sys
from threading import Event,Thread
import time


def main():
    p=argparse.ArgumentParser();p.add_argument('--name',required=True);p.add_argument('--duration',type=float,default=.5)
    p.add_argument('--service',action='store_true');p.add_argument('--result-timeout',type=float,default=40)
    args=p.parse_args()
    if not args.name.startswith('/vaf_phase3_') or not .05<=args.duration<=30 or not 0<args.result_timeout<=45:p.error('isolated bounded worker contract required')
    import rclpy
    from rclpy.action import ActionClient
    from nav2_msgs.action import Wait
    from std_srvs.srv import Trigger
    from uuid import uuid4
    cancelled=Event()
    def read_cancel():
        for line in sys.stdin:
            if line.strip()=='cancel':cancelled.set()
    Thread(target=read_cancel,daemon=True).start()
    def emit(state,**kw):print(json.dumps(dict(state=state,**kw)),flush=True)
    rclpy.init();node=rclpy.create_node('vaf_action_client_'+uuid4().hex[:10])
    client=None;accepted=False
    try:
        if args.service:
            client=node.create_client(Trigger,args.name)
            if not client.wait_for_service(timeout_sec=2):emit('FAILED',error='ROS service unavailable');return 1
            future=client.call_async(Trigger.Request());end=time.monotonic()+args.result_timeout
            while not future.done() and time.monotonic()<end:rclpy.spin_once(node,timeout_sec=.05)
            if not future.done():emit('UNKNOWN',error='ROS service response unconfirmed');return 1
            response=future.result();emit('SUCCEEDED' if response.success else 'FAILED',result={'message':response.message},error=None if response.success else response.message)
            return 0 if response.success else 1
        client=ActionClient(node,Wait,args.name)
        if not client.wait_for_server(timeout_sec=2):emit('FAILED',error='ROS Action Server unavailable before goal submission');return 1
        goal=Wait.Goal();goal.time.sec=int(args.duration);goal.time.nanosec=int((args.duration-int(args.duration))*1e9)
        def feedback(message):
            left=message.feedback.time_left
            emit('RUNNING',feedback={'time_left_s':left.sec+left.nanosec/1e9})
        sent=client.send_goal_async(goal,feedback_callback=feedback);until=time.monotonic()+2
        while not sent.done() and time.monotonic()<until:rclpy.spin_once(node,timeout_sec=.05)
        if not sent.done():emit('UNKNOWN',error='ROS goal admission response lost');return 1
        handle=sent.result()
        if not handle.accepted:emit('FAILED',error='ROS goal rejected');return 1
        accepted=True;emit('RUNNING',feedback={'accepted':True,'goal_id':[int(x) for x in handle.goal_id.uuid]})
        result=handle.get_result_async();end=time.monotonic()+args.result_timeout;cancel=None
        while not result.done() and time.monotonic()<end:
            if cancelled.is_set() and cancel is None:cancel=handle.cancel_goal_async()
            rclpy.spin_once(node,timeout_sec=.05)
        if not result.done():emit('UNKNOWN',error='ROS result deadline; server execution unconfirmed');return 1
        response=result.result();value=response.result
        state={4:'SUCCEEDED',5:'CANCELLED',6:'FAILED'}.get(response.status,'UNKNOWN')
        if value.error_code and state=='SUCCEEDED':state='FAILED'
        emit(state,result={'elapsed_s':value.total_elapsed_time.sec+value.total_elapsed_time.nanosec/1e9,
            'error_code':value.error_code},error=value.error_msg or None)
        return 0 if state in ('SUCCEEDED','CANCELLED') else 1
    except Exception as exc:
        emit('UNKNOWN' if accepted else 'FAILED',error='ROS worker communication failure: '+type(exc).__name__);return 1
    finally:
        if client is not None and not args.service:client.destroy()
        node.destroy_node();rclpy.shutdown()


if __name__=='__main__':raise SystemExit(main())
