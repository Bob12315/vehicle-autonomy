"""One public native SerializePoseGraph RPC into an explicit private map root.

No motion port, truth source or implicit retry. A lost service result is UNKNOWN.
This storage helper alone is not an external lifecycle/vehicle release proof.
"""
import argparse
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True);parser.add_argument('--name',required=True);parser.add_argument('--result',type=Path,required=True);a,ros_args=parser.parse_known_args()
    from vehicle_autonomy.world.mapping.native_files import prepare_native_map,inspect_native_map
    base,_=prepare_native_map(a.directory,a.name)
    import rclpy
    from rclpy.node import Node
    from slam_toolbox.srv import SerializePoseGraph
    rclpy.init(args=ros_args);node=Node('vaf_slam_storage',start_parameter_services=False);result=dict(schema=1,state='FAILED',request_sent=False)
    try:
        client=node.create_client(SerializePoseGraph,'/slam_toolbox/serialize_map')
        if not client.wait_for_service(timeout_sec=15):raise TimeoutError('native map storage service unavailable')
        request=SerializePoseGraph.Request();request.filename=str(base)
        result.update(state='UNKNOWN',request_sent=True)
        future=client.call_async(request);rclpy.spin_until_future_complete(node,future,timeout_sec=15)
        if not future.done() or future.cancelled():raise TimeoutError('native map storage result lost; not retried')
        response=future.result()
        if response.result!=SerializePoseGraph.Response.RESULT_SUCCESS:raise ValueError('native storage did not confirm success')
        files=inspect_native_map(a.directory,a.name)
        result.update(state='SUCCEEDED',files=files,base=str(base))
    except Exception as exc:result['error']=type(exc).__name__+': '+str(exc)
    finally:a.result.write_text(json.dumps(result,indent=2)+'\n');node.destroy_node();rclpy.shutdown()
    return 0 if result['state']=='SUCCEEDED' else 1

if __name__=='__main__':raise SystemExit(main())
