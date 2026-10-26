"""One public lifecycle transition, once. Lost result is UNKNOWN, never retried."""
import argparse
import json
from pathlib import Path
import re
import time


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--node',required=True);p.add_argument('--transition',choices=('configure','activate','deactivate','cleanup'),required=True);p.add_argument('--result',type=Path,required=True);a,ros_args=p.parse_known_args()
    if not re.fullmatch('/[a-zA-Z0-9_/]+',a.node):raise ValueError('absolute native node required')
    import rclpy
    from rclpy.node import Node
    from lifecycle_msgs.srv import GetState,ChangeState
    rclpy.init(args=ros_args);node=Node('vaf_lifecycle_client',start_parameter_services=False)
    result=dict(schema=1,node=a.node,transition=a.transition,state='FAILED',request_sent=False)
    operations={'configure':(1,1,2),'activate':(3,2,3),'deactivate':(4,3,2),'cleanup':(2,2,1)}
    def call(client,request):
        if not client.wait_for_service(timeout_sec=15):raise TimeoutError('native lifecycle endpoint unavailable')
        future=client.call_async(request);rclpy.spin_until_future_complete(node,future,timeout_sec=15)
        if not future.done() or future.cancelled():raise TimeoutError('native lifecycle result not received')
        return future.result()
    try:
        get=node.create_client(GetState,a.node+'/get_state');change=node.create_client(ChangeState,a.node+'/change_state')
        transition,expected,final=operations[a.transition]
        actual=call(get,GetState.Request()).current_state.id
        if actual!=expected:raise ValueError('native lifecycle precondition mismatch')
        request=ChangeState.Request();request.transition.id=transition
        # Register dispatch intent before calling: a client exception may follow
        # a server-side state change. No automatic resubmission is permitted.
        result.update(state='UNKNOWN',request_sent=True)
        response=call(change,request)
        if not response.success:raise ValueError('native transition rejected')
        actual=call(get,GetState.Request()).current_state.id
        if actual!=final:raise ValueError('native lifecycle postcondition unconfirmed')
        result.update(state='SUCCEEDED',native_state=actual)
    except Exception as exc:result['error']=type(exc).__name__+': '+str(exc)
    finally:
        a.result.write_text(json.dumps(result,indent=2));node.destroy_node();rclpy.shutdown()
    return 0 if result['state']=='SUCCEEDED' else 1


if __name__=='__main__':raise SystemExit(main())
