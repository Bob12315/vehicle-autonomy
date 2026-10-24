"""Real isolated DDS ActionServer; timers only, no navigation or vehicle access."""
import argparse
import json
import time
import signal


def main():
    p=argparse.ArgumentParser();p.add_argument('--prefix',required=True);args=p.parse_args()
    if not args.prefix.startswith('/vaf_phase3_'):p.error('isolated namespace required')
    import rclpy
    from rclpy.action import ActionServer,CancelResponse
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.executors import MultiThreadedExecutor
    from nav2_msgs.action import Wait
    from std_srvs.srv import Trigger
    from uuid import uuid4
    rclpy.init();node=rclpy.create_node('vaf_test_server_'+uuid4().hex[:10]);group=ReentrantCallbackGroup()
    def execute(handle,behavior):
        duration=handle.request.time.sec+handle.request.time.nanosec/1e9
        start=time.monotonic()
        while time.monotonic()-start<duration:
            if handle.is_cancel_requested:
                handle.canceled();return Wait.Result()
            if behavior=='disconnect' and time.monotonic()-start>.3:
                # Real server process loss: the client cannot infer remote stop.
                __import__('os')._exit(2)
            left=max(0,duration-(time.monotonic()-start));feedback=Wait.Feedback()
            feedback.time_left.sec=int(left);feedback.time_left.nanosec=int((left-int(left))*1e9)
            handle.publish_feedback(feedback);time.sleep(.05)
        result=Wait.Result();elapsed=time.monotonic()-start
        result.total_elapsed_time.sec=int(elapsed);result.total_elapsed_time.nanosec=int((elapsed-int(elapsed))*1e9)
        if behavior=='error':result.error_code=1;result.error_msg='intentional test error';handle.abort()
        else:handle.succeed()
        return result
    servers=[ActionServer(node,Wait,args.prefix+'/'+behavior,lambda h,b=behavior:execute(h,b),
        cancel_callback=lambda _:CancelResponse.ACCEPT,callback_group=group) for behavior in ('normal','error','disconnect')]
    def service(request,response):response.success=True;response.message='real isolated ROS Trigger response';return response
    node.create_service(Trigger,args.prefix+'/trigger',service,callback_group=group)
    print(json.dumps({'ready':True}),flush=True)
    executor=MultiThreadedExecutor(num_threads=4);executor.add_node(node)
    try:executor.spin()
    except KeyboardInterrupt:pass
    finally:
        executor.shutdown(timeout_sec=2)
        for server in servers:server.destroy()
        node.destroy_node();rclpy.shutdown()


if __name__=='__main__':main()
