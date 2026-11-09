"""Display a verified resource; optional resource alias TF, never a robot pose."""
import argparse,hashlib,json,signal,time
from array import array
from pathlib import Path
from vehicle_autonomy.world.mapping.cloud_maps import read_pcd


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);args=parser.parse_args()
    cfg=json.loads(args.config.read_text());data=args.config.with_name('map.pcd').read_bytes()
    if hashlib.sha256(data).hexdigest()!=cfg['sha256']:raise ValueError('loaded display map changed')
    values=read_pcd(data)
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile,DurabilityPolicy,ReliabilityPolicy
    from sensor_msgs.msg import PointCloud2,PointField
    from tf2_msgs.msg import TFMessage
    from geometry_msgs.msg import TransformStamped
    rclpy.init(args=[]);node=Node('vaf_saved_map',namespace=cfg['namespace'])
    qos=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE)
    pub=node.create_publisher(PointCloud2,cfg['namespace']+'/loaded_map',qos)
    anchor=node.create_publisher(TFMessage,cfg['namespace']+'/tf_static',qos) if cfg.get('anchor_enabled',True) else None
    frame=TransformStamped();frame.header.frame_id=cfg['frame_id'];frame.child_frame_id=cfg['frame_id']+'/pcd_snapshot'
    frame.transform.rotation.w=1.
    msg=PointCloud2();msg.header.frame_id=frame.child_frame_id if anchor else cfg['frame_id'];msg.height=1;msg.width=len(values)
    msg.fields=[PointField(name=n,offset=i*4,datatype=PointField.FLOAT32,count=1) for i,n in enumerate(('x','y','z','intensity'))]
    msg.point_step=16;msg.row_step=len(values)*16;msg.is_dense=True;msg.data=array('B',values.tobytes());stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    try:
        while not stopped:
            # A resource-coordinate alias only, no robot pose or localization.
            if anchor:anchor.publish(TFMessage(transforms=[frame]))
            pub.publish(msg)
            rclpy.spin_once(node,timeout_sec=.1);time.sleep(.4)
    finally:node.destroy_node();rclpy.shutdown()


if __name__=='__main__':main()
