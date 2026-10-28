"""Synthetic stationary ROS test inputs; never a real sensor or control source."""
import math
import signal


def main():
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile,DurabilityPolicy,ReliabilityPolicy
    from geometry_msgs.msg import TransformStamped
    from nav_msgs.msg import OccupancyGrid,Odometry
    from sensor_msgs.msg import LaserScan
    from tf2_msgs.msg import TFMessage
    from tf2_ros import TransformBroadcaster,StaticTransformBroadcaster
    rclpy.init(args=[]);node=Node('vaf_synthetic_world',namespace='/rover')
    stop=False
    def stopping(*_):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGTERM,stopping);signal.signal(signal.SIGINT,stopping)
    latched=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE)
    maps=[node.create_publisher(OccupancyGrid,name,latched) for name in ('/map','/rover/map')]
    odoms=[node.create_publisher(Odometry,name,10) for name in ('/odom','/rover/odom')]
    scans=[node.create_publisher(LaserScan,name,10) for name in ('/scan','/rover/scan')]
    tf=TransformBroadcaster(node);static=StaticTransformBroadcaster(node)
    ns_tf=node.create_publisher(TFMessage,'/rover/tf',10);ns_static=node.create_publisher(TFMessage,'/rover/tf_static',latched)
    def transform(parent,child):
        message=TransformStamped();message.header.frame_id=parent;message.child_frame_id=child;message.transform.rotation.w=1.
        message.header.stamp=node.get_clock().now().to_msg();return message
    static_messages=[transform('map','odom'),transform('base_link','laser')]
    static.sendTransform(static_messages);ns_static.publish(TFMessage(transforms=static_messages))
    def publish():
        stamp=node.get_clock().now().to_msg();pose=transform('odom','base_link');tf.sendTransform(pose);ns_tf.publish(TFMessage(transforms=[pose]))
        grid=OccupancyGrid();grid.header.frame_id='map';grid.header.stamp=stamp;grid.info.width=80;grid.info.height=80;grid.info.resolution=.25
        grid.info.origin.position.x=-10.;grid.info.origin.position.y=-10.;grid.info.origin.orientation.w=1.;grid.data=[0]*6400
        for pub in maps:pub.publish(grid)
        odom=Odometry();odom.header.frame_id='odom';odom.child_frame_id='base_link';odom.header.stamp=stamp;odom.pose.pose.orientation.w=1.
        for pub in odoms:pub.publish(odom)
        scan=LaserScan();scan.header.frame_id='laser';scan.header.stamp=stamp;scan.angle_min=-math.pi;scan.angle_max=math.pi;scan.angle_increment=math.pi/180
        scan.range_min=.1;scan.range_max=20.;scan.ranges=[10.]*361
        for pub in scans:pub.publish(scan)
    timer=node.create_timer(.05,publish)
    print('SYNTHETIC map/TF/scan/odom fixture; no vehicle or navigation goal',flush=True)
    try:
        while not stop:rclpy.spin_once(node,timeout_sec=.1)
    finally:node.destroy_timer(timer);node.destroy_node();rclpy.shutdown()


if __name__=='__main__':main()
