"""Read-only bounded observation of actual SC-PGO output, no controller inputs."""
import argparse,json,time
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--sensor',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=5.);a=p.parse_args();c=json.loads(a.sensor.read_text())
    import rclpy
    from rclpy.node import Node
    from nav_msgs.msg import Path as RosPath
    from sensor_msgs.msg import PointCloud2
    from sensor_msgs_py import point_cloud2
    from vehicle_autonomy.world.mapping.cloud_maps import pcd_bytes
    from vehicle_autonomy.contracts.core.geometry import Quaternion,Vector3
    from vehicle_autonomy.world.transform.tree import rotate_vector
    import numpy as np
    rclpy.init(args=[]);node=Node('vaf_pgo_acceptance_judge');latest=None;cloud=None;prefix=c['namespace']+'/slam/pgo'
    def rotate(q,p):
        value=rotate_vector(q,Vector3(*map(float,p)));return np.array([value.x,value.y,value.z])
    def trajectory(message):
        nonlocal latest
        latest=message
    def points(message):
        nonlocal cloud
        cloud=message
    node.create_subscription(RosPath,prefix+'/trajectory',trajectory,10)
    node.create_subscription(PointCloud2,prefix+'/map',points,10)
    deadline=time.monotonic()+min(max(a.seconds,1.),600.)
    try:
        while time.monotonic()<deadline:rclpy.spin_once(node,timeout_sec=.02)
        poses=[]
        if latest:
            for v in latest.poses:
                q=v.pose.orientation;p=v.pose.position;quat=[q.x,q.y,q.z,q.w]
                xyz=np.array([p.x,p.y,p.z])-rotate(Quaternion(*quat),np.array(c['mount'][:3])+np.array(c['imu_in_lidar'][:3]))
                poses.append(dict(capture_ros_ns=v.header.stamp.sec*1_000_000_000+v.header.stamp.nanosec,
                    position=xyz.tolist(),quaternion=quat))
        a.output.mkdir(mode=0o700,parents=True,exist_ok=False)
        (a.output/'poses.json').write_text(json.dumps(poses)+'\n')
        details=dict(poses=len(poses),tf_publishers=len(node.get_publishers_info_by_topic(prefix+'/unused_tf')))
        if cloud and cloud.width:
            values=point_cloud2.read_points_numpy(cloud,field_names=('x','y','z','intensity'),skip_nans=True)
            (a.output/'map.pcd').write_bytes(pcd_bytes(values));details.update(points=cloud.width,
                map_capture_ros_ns=cloud.header.stamp.sec*1_000_000_000+cloud.header.stamp.nanosec,
                map_frame=cloud.header.frame_id)
        (a.output/'observation.json').write_text(json.dumps(details,indent=2)+'\n')
    finally:node.destroy_node();rclpy.shutdown()


if __name__=='__main__':main()
