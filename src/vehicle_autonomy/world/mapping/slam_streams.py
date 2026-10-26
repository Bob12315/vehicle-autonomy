"""Read-only native SLAM estimates. No truth input, odom publisher or writer."""
import argparse
from collections import deque
from datetime import datetime,timezone,timedelta
import json
import math
from pathlib import Path
import signal
import time
from uuid import uuid4

from vehicle_autonomy.contracts.core.geometry import Pose3,Vector3,Quaternion
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.streams import SampleHeader,StreamObservation,DataKind,SourceKind,FrameDescriptor
from vehicle_autonomy.world.mapping.clock import RosClockBridge
from vehicle_autonomy.world.mapping.grid import OccupancyGrid,atomic_json,pose_to_json
from vehicle_autonomy.world.sensors.stream_store import StreamStore


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);a,ros_args=p.parse_known_args()
    c=json.loads(a.config.read_text())
    if set(c)!={'schema','directory','source_id','frame_epoch','map_epoch','calibration_version'} or c['schema']!=1:raise ValueError('explicit SLAM stream profile required')
    root=Path(c['directory']);root.mkdir(mode=0o700,parents=True,exist_ok=True)
    store=StreamStore(root/'payloads',slots=6,max_bytes=2_000_000);epoch=uuid4().hex;clock=RosClockBridge()
    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.clock import Clock,ClockType
    from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy
    from rclpy.signals import SignalHandlerOptions
    from rosgraph_msgs.msg import Clock as RosClock
    from nav_msgs.msg import OccupancyGrid as RosGrid
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from tf2_ros import Buffer,TransformListener
    stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    rclpy.init(args=ros_args,signal_handler_options=SignalHandlerOptions.NO)
    def ns(stamp):return stamp.sec*1_000_000_000+stamp.nanosec
    def at(value):return TimePoint(value,datetime.now(timezone.utc)-timedelta(microseconds=(time.monotonic_ns()-value)//1000),'host-monotonic-simulation')
    def pose(m):return Pose3(Vector3(m.position.x,m.position.y,m.position.z),Quaternion(m.orientation.x,m.orientation.y,m.orientation.z,m.orientation.w))
    class Reader(Node):
        def __init__(self):
            super().__init__('vaf_slam_streams',parameter_overrides=[Parameter('use_sim_time',value=True)])
            self.buffer=Buffer(node=self);self.listener=TransformListener(self.buffer,self)
            self.pending={k:deque(maxlen=2) for k in ('map','slam_pose')};self.latest={};self.counts={};self.dropped={};self.pins={};self.last_source={};self.fault=None;self.shape=None;self.clock_host=None;self.last_transform=None;self.waiting=None;self.tf_pins={};self.observed_tf=[]
            qos=QoSProfile(depth=2,reliability=ReliabilityPolicy.BEST_EFFORT)
            maps=QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL)
            self.create_subscription(RosClock,'/clock',self.on_clock,qos)
            self.create_subscription(RosGrid,'/map',lambda m:self.enqueue('map',m),maps)
            self.create_subscription(PoseWithCovarianceStamped,'/pose',lambda m:self.enqueue('slam_pose',m),10)
            self.create_timer(.04,self.tick,clock=Clock(clock_type=ClockType.STEADY_TIME))
        def on_clock(self,m):
            if clock.observe(ns(m.clock),time.monotonic_ns()):self.fault='clock epoch changed; explicit readmission required'
            self.clock_host=clock.pairs[-1][1] if clock.pairs else None
        def enqueue(self,key,m):
            topic='/map' if key=='map' else '/pose';publishers=self.get_publishers_info_by_topic(topic)
            if len(publishers)!=1 or publishers[0].node_name!='slam_toolbox':
                self.dropped[key]=self.dropped.get(key,0)+1;return
            gid=bytes(publishers[0].endpoint_gid).hex()
            if key in self.pins and self.pins[key]!=gid:self.fault='native SLAM publisher epoch changed; restart reader';return
            self.pins[key]=gid
            if m.header.frame_id!='map':self.fault='SLAM frame mismatch';return
            q=self.pending[key]
            if len(q)==q.maxlen:self.dropped[key]=self.dropped.get(key,0)+1
            q.append((m,time.monotonic_ns()))
        def publish(self,key,kind,stamp,received,capture,value,covariance=()):
            sequence=self.counts.get(key,0)+1
            ref=store.put(json.dumps(value,separators=(',',':'),allow_nan=False).encode(),'application/vnd.vehicle-autonomy.'+key,channel=key)
            h=SampleHeader(c['source_id'],key,kind,epoch,sequence,stamp,'ros-simulation:'+clock.epoch,at(received),at(capture),FrameDescriptor('map','ENU',c['map_epoch']),c['calibration_version'],SourceKind.SIMULATION,QualityState.VALID,covariance=covariance)
            self.latest[key]=to_json_value(StreamObservation(h,ref));self.counts[key]=sequence
        def consume(self,key,m,received,capture):
            source=ns(m.header.stamp);instant=rclpy.time.Time.from_msg(m.header.stamp)
            if not self.buffer.can_transform('map','base_link',instant) or not self.buffer.can_transform('map','odom',instant):raise LookupError('time-matched map transforms unavailable')
            if key=='map':
                grid=OccupancyGrid('map',float(m.info.resolution),m.info.width,m.info.height,pose(m.info.origin),tuple(int(v) for v in m.data))
                self.publish(key,DataKind.MAP,source,received,capture,grid.document())
                self.shape=dict(width=grid.width,height=grid.height,resolution=grid.resolution_m,known=sum(v>=0 for v in grid.cells),occupied=sum(v>=65 for v in grid.cells))
            else:
                cov=tuple(float(v) for v in m.pose.covariance)
                estimate=pose(m.pose.pose)
                if not all(math.isfinite(v) for v in cov) or any(cov[i]<0 or cov[i]>.25 for i in (0,7,35)):raise ValueError('localization covariance invalid/unqualified')
                transform=self.buffer.lookup_transform('map','odom',instant).transform
                value=dict(translation=[transform.translation.x,transform.translation.y,transform.translation.z],rotation=[transform.rotation.x,transform.rotation.y,transform.rotation.z,transform.rotation.w],parent='map',child='odom',interpolated_at_source_stamp=True)
                if self.last_transform:
                    old=self.last_transform
                    if math.dist(old['translation'],value['translation'])>.5:
                        self.fault='map to odom jump; explicit localization reset required';raise ValueError(self.fault)
                    dot=abs(sum(x*y for x,y in zip(old['rotation'],value['rotation'])))
                    if 2*math.acos(min(1.,dot))>.35:
                        self.fault='map to odom rotation jump; explicit localization reset required';raise ValueError(self.fault)
                self.publish('map_transform',DataKind.TRANSFORM,source,received,capture,value)
                self.publish(key,DataKind.SLAM_POSE,source,received,capture,dict(pose=pose_to_json(estimate),covariance=cov),cov)
                self.last_transform=value
        def tick(self):
            now=time.monotonic_ns();error=self.fault;self.waiting=None
            try:
                if error:raise ValueError(error)
                if self.clock_host is None or now-self.clock_host>500_000_000:raise ValueError('ROS clock unavailable')
                publishers=self.get_publishers_info_by_topic('/tf')
                self.observed_tf=[dict(name=p.node_name,namespace=p.node_namespace,gid=bytes(p.endpoint_gid).hex()) for p in publishers[:8]]
                grouped={}
                for publisher in publishers:
                    name=publisher.node_namespace.rstrip('/')+'/'+publisher.node_name
                    grouped.setdefault(name,[]).append(bytes(publisher.endpoint_gid).hex())
                valid=(set(grouped)=={'/slam_toolbox','/vaf_world_streams'}
                    and len(grouped['/vaf_world_streams'])==1 and 1<=len(grouped['/slam_toolbox'])<=2
                    and len({gid[:24] for gid in grouped['/slam_toolbox']})==1)
                if not valid:
                    if self.last_transform is not None:self.fault='TF authority graph changed; explicit readmission required'
                    raise ValueError('expected unique AP and native SLAM TF participants')
                # Native SLAM 2.8.5 owns a main broadcaster and a separate
                # LoopClosureAssistant broadcaster in the SAME participant.
                # Endpoint count alone does not indicate duplicate TF authority.
                pins={name:sorted(gids) for name,gids in grouped.items()}
                if self.tf_pins and pins!=self.tf_pins:
                    self.fault='TF publisher epoch changed; explicit readmission required';raise ValueError(self.fault)
                self.tf_pins=pins
                for key,q in self.pending.items():
                    while q:
                        m,received=q[0];source=ns(m.header.stamp)
                        if source<=self.last_source.get(key,-1) or now-received>500_000_000:q.popleft();self.dropped[key]=self.dropped.get(key,0)+1;continue
                        try:
                            capture=clock.to_host(source)
                            if capture>received:
                                if capture-received>20_000_000:raise ValueError('clock/source chronology')
                                capture=received
                            if now-capture>500_000_000:raise ValueError('SLAM source expired')
                            self.consume(key,m,received,capture)
                        except LookupError as exc:self.waiting=str(exc);break
                        q.popleft();self.last_source[key]=source
            except ValueError as exc:error=str(exc)
            atomic_json(root/'state.json',dict(schema=1,generation=epoch,source_kind='simulation',source_id=c['source_id'],origin_id=c['frame_epoch'],ap_world_epoch=c['frame_epoch'],published_ns=now,error=error,streams=self.latest,shape=self.shape,publishers=self.pins,tf_publishers=self.tf_pins,observed_tf=self.observed_tf,counts=self.counts,dropped=self.dropped,queue_depths={k:len(q) for k,q in self.pending.items()},waiting=self.waiting))
    node=Reader()
    try:
        while rclpy.ok() and not stopped:rclpy.spin_once(node,timeout_sec=.05)
    finally:
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
        atomic_json(root/'stopped.json',dict(stopped=True,generation=epoch,at_ns=time.monotonic_ns()))


if __name__=='__main__':main()
