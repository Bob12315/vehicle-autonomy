"""Optional ROS 2 visualization sidecar; no MAVLink, cmd_vel or Nav2 client."""
import argparse
import json
import math
from pathlib import Path
import signal
import time
from uuid import uuid4

from .config import frames,load,vehicle_context
from .projection import Projection
from .source import Source
from vehicle_autonomy.world.mapping.clock import RosClockBridge
from vehicle_autonomy.world.mapping.grid import atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args();config=load(args.config);ctx=vehicle_context();names=frames(ctx,config)
    # ROS stays confined to this explicitly launched process.
    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.clock import Clock,ClockType
    from rclpy.qos import QoSProfile,DurabilityPolicy,ReliabilityPolicy
    from builtin_interfaces.msg import Time as Stamp
    from builtin_interfaces.msg import Duration
    from geometry_msgs.msg import PoseStamped,TransformStamped,Point
    from nav_msgs.msg import Odometry,Path as RosPath
    from rosgraph_msgs.msg import Clock as RosClock
    from sensor_msgs.msg import NavSatFix,NavSatStatus
    from std_msgs.msg import String
    from tf2_msgs.msg import TFMessage
    from visualization_msgs.msg import Marker,MarkerArray

    def stamp(value):s=Stamp();s.sec,s.nanosec=divmod(value,1_000_000_000);return s
    def pose(message,value):
        for k,v in zip(('x','y','z'),value['position']):setattr(message.position,k,v)
        for k,v in zip(('x','y','z','w'),value['orientation']):setattr(message.orientation,k,v)
    def vector(message,value):message.x=value.x;message.y=value.y;message.z=value.z
    def at(x,y,z):p=Point();p.x=float(x);p.y=float(y);p.z=float(z);return p

    rclpy.init(args=[]);stopped=False
    def stopping(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGINT,stopping);signal.signal(signal.SIGTERM,stopping)
    qos=QoSProfile(depth=5,reliability=ReliabilityPolicy.RELIABLE)
    retained=QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL)

    class Visualization(Node):
        def __init__(self):
            super().__init__('vaf_visualization_bridge',namespace=names['namespace'] or '/',parameter_overrides=[Parameter('use_sim_time',value=config.get('use_sim_time',False))])
            self.source=Source(config,ctx['vehicle_id']);self.projection=Projection(ctx['vehicle_id'],ctx['vehicle_type'])
            self.mapper=RosClockBridge();self.last_clock=None;self.last_wall=None;self.wall_fault=None
            self.origin_epoch=None;self.origin_history=[];self.sequence=0;self.valid=False;self.reason='waiting for source';self.last_reset=-1;self.last_status=0;self.last_gps=None;self.sample_age=None
            self.odom=self.create_publisher(Odometry,names['topic']+'/odometry',qos)
            self.path=self.create_publisher(RosPath,names['topic']+'/trajectory',qos)
            self.fix=self.create_publisher(NavSatFix,names['topic']+'/gps/fix',qos)
            self.markers=self.create_publisher(MarkerArray,names['topic']+'/markers',qos)
            self.status=self.create_publisher(String,names['topic']+'/status',retained)
            self.tf=None if config.get('external') else self.create_publisher(TFMessage,names['tf'],qos)
            self.create_subscription(PoseStamped,names['topic']+'/pending_goal',self.goal,qos)
            if config.get('use_sim_time'):self.create_subscription(RosClock,'/clock',self.clock_update,qos)
            self.create_timer(.05,self.tick,clock=Clock(clock_type=ClockType.STEADY_TIME))

        def clock_update(self,message):
            now=time.monotonic_ns();value=message.clock.sec*1_000_000_000+message.clock.nanosec
            previous=self.mapper.pairs[-1] if self.mapper.pairs else None
            if self.mapper.observe(value,now):self.projection.clear();self.projection.fault=None;self.blank('ROS clock epoch changed')
            if not previous or value!=previous[0]:self.last_clock=now

        def map_stamp(self,capture):
            if config.get('use_sim_time'):
                if self.last_clock is None or time.monotonic_ns()-self.last_clock>500_000_000:raise ValueError('ROS simulation clock absent or paused')
                return self.mapper.to_ros(capture)
            if self.wall_fault:raise ValueError(self.wall_fault)
            return self.get_clock().now().nanoseconds-(time.monotonic_ns()-capture)

        def blank(self,reason):
            self.valid=False;self.reason=reason;self.projection.path.clear()
            path=RosPath();path.header.frame_id=names['odom'];path.header.stamp=self.get_clock().now().to_msg();self.path.publish(path)
            array=MarkerArray();delete=Marker();delete.action=Marker.DELETEALL;array.markers.append(delete)
            text=Marker();text.header.frame_id=names['fixed'];text.header.stamp=path.header.stamp;text.ns='vaf_status';text.id=900;text.type=Marker.TEXT_VIEW_FACING;text.action=Marker.ADD
            text.pose.orientation.w=1.;text.pose.position.z=1.;text.scale.z=.3;text.color.r=1.;text.color.g=.25;text.color.b=.2;text.color.a=1.;text.text='NO CURRENT POSITION\n'+reason[:150];text.lifetime=Duration(sec=1);array.markers.append(text);self.markers.publish(array)
            fix=NavSatFix();fix.header=path.header;fix.status.status=NavSatStatus.STATUS_NO_FIX;fix.latitude=fix.longitude=fix.altitude=float('nan');self.fix.publish(fix)

        def publish(self,value):
            odom=Odometry();odom.header.frame_id=names['odom'];odom.header.stamp=stamp(value['stamp_ns']);odom.child_frame_id=names['base'];pose(odom.pose.pose,value)
            vector(odom.twist.twist.linear,value['body_linear']);vector(odom.twist.twist.angular,value['body_angular'])
            for i in (0,7,14,21,28,35):odom.pose.covariance[i]=odom.twist.covariance[i]=1e6  # Source covariance not supplied; never claim perfect accuracy.
            self.odom.publish(odom)
            if self.tf:
                t=TransformStamped();t.header=odom.header;t.child_frame_id=names['base'];t.transform.translation.x,t.transform.translation.y,t.transform.translation.z=value['position'];t.transform.rotation=odom.pose.pose.orientation
                packet=TFMessage();packet.transforms=[t];self.tf.publish(packet)
            path=RosPath();path.header=odom.header
            for item in self.projection.path:
                p=PoseStamped();p.header.frame_id=names['odom'];p.header.stamp=stamp(item['stamp_ns']);pose(p.pose,item);path.poses.append(p)
            self.path.publish(path)
            array=MarkerArray()
            body=Marker();body.header=odom.header;body.ns='live_vehicle';body.id=0;body.type=Marker.ARROW;body.action=Marker.ADD;body.pose=odom.pose.pose
            body.scale.x=1.2 if ctx['vehicle_type']=='plane' else .65;body.scale.y=.2;body.scale.z=.2;body.color.r=.15;body.color.g=.85;body.color.b=.75;body.color.a=1.;body.lifetime=Duration(sec=3,nanosec=200_000_000);array.markers.append(body)
            if value['ekf_health']=='UNKNOWN':body.color.r=1.;body.color.g=.65;body.color.b=.1
            text=Marker();text.header=odom.header;text.ns='live_vehicle';text.id=1;text.type=Marker.TEXT_VIEW_FACING;text.action=Marker.ADD;text.pose.orientation.w=1.
            text.pose.position=at(*[v+(1. if i==2 else 0.) for i,v in enumerate(value['position'])]);text.scale.z=.18;text.color.r=text.color.g=text.color.b=text.color.a=1.;text.lifetime=body.lifetime
            speed=math.sqrt(sum(v*v for v in (value['world_linear'].x,value['world_linear'].y,value['world_linear'].z)))
            text.text=f"{ctx['vehicle_id']} · AP reported pose (not SLAM)\nU {value['position'][2]:.2f} m · {speed:.2f} m/s\nSample age {value['age_s']:.2f} s · EKF {value['ekf_health']}";array.markers.append(text)
            velocity=Marker();velocity.header=odom.header;velocity.ns='live_vehicle';velocity.id=2;velocity.type=Marker.ARROW;velocity.action=Marker.ADD;velocity.pose.orientation.w=1.;velocity.scale.x=.04;velocity.scale.y=.09;velocity.scale.z=.12
            velocity.color.r=1.;velocity.color.g=.65;velocity.color.b=.1;velocity.color.a=1.;velocity.lifetime=body.lifetime
            p=value['position'];v=value['world_linear'];velocity.points=[at(*p),at(p[0]+v.x,p[1]+v.y,p[2]+v.z)];array.markers.append(velocity);self.markers.publish(array)
            gps=value['gps'];fix=NavSatFix();fix.header.stamp=odom.header.stamp;fix.header.frame_id=names['base'];fix.altitude=float('nan')
            if gps and value['gps_stamp_ns'] is not None:
                fix.header.stamp=stamp(value['gps_stamp_ns'])
                fix.latitude=gps['latitude_deg'];fix.longitude=gps['longitude_deg'];fix.status.status=NavSatStatus.STATUS_FIX;fix.status.service=NavSatStatus.SERVICE_GPS
            else:fix.latitude=fix.longitude=float('nan');fix.status.status=NavSatStatus.STATUS_NO_FIX
            fix.position_covariance_type=NavSatFix.COVARIANCE_TYPE_UNKNOWN
            if not gps or value['gps_sample_ns']!=self.last_gps:self.fix.publish(fix);self.last_gps=value['gps_sample_ns']
            self.sequence+=1;self.valid=True;self.reason=None;self.sample_age=value['age_s']

        def goal(self,message):
            try:
                original=message.header.frame_id
                if not self.valid or original not in ({names['odom'],names['fixed']} if config.get('external') else {names['odom']}):raise ValueError('pending goal frame or live localization invalid')
                when=message.header.stamp.sec*1_000_000_000+message.header.stamp.nanosec
                if not 0<=self.get_clock().now().nanoseconds-when<=500_000_000:raise ValueError('pending goal timestamp stale/future')
                p=message.pose.position;q=message.pose.orientation
                self.source.enqueue(dict(id=uuid4().hex,target=ctx['vehicle_id'],epoch=self.projection.epoch,frame='odom' if original==names['odom'] else 'map',ros_frame=original,position=[p.x,p.y,p.z],orientation=[q.x,q.y,q.z,q.w]))
            except ValueError as exc:self.get_logger().warning(str(exc))

        def tick(self):
            now=time.monotonic_ns();latest,error,proposal=self.source.read()
            try:
                ros=self.get_clock().now().nanoseconds
                if not config.get('use_sim_time'):
                    if self.last_wall and abs((ros-self.last_wall[0])-(now-self.last_wall[1]))>500_000_000:self.wall_fault='ROS/system clock jumped; restart visualization'
                    self.last_wall=(ros,now)
                    if self.wall_fault:raise ValueError(self.wall_fault)
                elif self.last_clock is None or now-self.last_clock>500_000_000:raise ValueError('ROS simulation clock absent or paused')
                if error or latest is None:raise ValueError(error or 'waiting for source')
                source,received,rtt=latest
                if source.get('environment')!=ctx['environment']:raise ValueError('vehicle environment mismatch')
                external=config.get('external')
                if external and source['epoch']!=external['origin_id']:raise ValueError('external TF origin binding no longer valid')
                if self.count_publishers(names['topic']+'/odometry')>1 or self.tf and self.count_publishers(names['tf'])>1:raise ValueError('conflicting visualization Odometry/TF publisher')
                value=self.projection.accept(source,received_ns=received,roundtrip_s=rtt,now_ns=now,stamp_for=self.map_stamp)
                if self.origin_epoch!=self.projection.epoch:
                    self.origin_epoch=self.projection.epoch;self.origin_history=(self.origin_history+[source['origin']])[-4:]
                    atomic_json(Path.cwd()/'origin.json',dict(schema=1,current=source['origin'],history=self.origin_history,coordinate_policy='upstream ENU; no second GPS/NED conversion'))
                if self.last_reset!=self.projection.resets:self.blank('origin/time/history reset');self.last_reset=self.projection.resets
                if value:self.publish(value)
            except (ValueError,KeyError,TypeError,LookupError,OverflowError) as exc:self.blank(str(exc))
            if now-self.last_status>200_000_000:
                result=dict(schema=1,vehicle_id=ctx['vehicle_id'],vehicle_type=ctx['vehicle_type'],valid=self.valid,reason=self.reason,sequence=self.sequence,epoch=self.projection.epoch,
                    stamp_ns=str(self.get_clock().now().nanoseconds),sample_age_s=self.sample_age,max_age_s=3.,use_sim_time=config.get('use_sim_time',False),frames=names,path_samples=len(self.projection.path),proposal=proposal,
                    source='existing Framework VehicleState; visualization only',tf_owner='external' if config.get('external') else 'isolated bridge',covariance='unknown; conservative large odometry covariance')
                message=String();message.data=json.dumps(result,allow_nan=False);self.status.publish(message);atomic_json(Path.cwd()/'visualization.json',result);self.last_status=now

    node=Visualization()
    try:
        while rclpy.ok() and not stopped:rclpy.spin_once(node,timeout_sec=.05)
    finally:
        node.blank('visualization stopped');node.source.close();node.destroy_node()
        if rclpy.ok():rclpy.shutdown()


if __name__=='__main__':main()
