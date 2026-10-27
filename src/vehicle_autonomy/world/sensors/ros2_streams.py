"""Explicit ROS sensor/AP read-only sidecar. No command subscription or writer.

Only a fresh owned simulation profile is accepted here. The existing ClockBridge
interpolates source times, never extrapolates or uses receipt as capture time.
"""
import argparse
from collections import deque
import copy
from datetime import datetime,timezone,timedelta
import json
import math
import os
from pathlib import Path
import signal
import stat
from threading import Event,Thread
import time
from urllib.parse import urlsplit,quote
from urllib.request import Request,urlopen
from uuid import uuid4

from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.streams import SampleHeader,StreamObservation,DataKind,SourceKind,FrameDescriptor
from vehicle_autonomy.world.mapping.clock import RosClockBridge
from vehicle_autonomy.world.mapping.grid import atomic_json
from vehicle_autonomy.world.sensors.stream_store import StreamStore


class VehicleProbe:
    def __init__(self,base,target,token_file):
        url=urlsplit(base)
        if url.scheme!='http' or url.hostname!='127.0.0.1' or not url.port or url.path or url.query or url.username or url.password:
            raise ValueError('explicit loopback simulation API required')
        path=Path(token_file);info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077:raise ValueError('private owned token file required')
        self._token=path.read_text().strip();self.url=base+'/api/world/vehicle?target='+quote(target,safe='')+'&projection=ap'
        self.latest=None;self.error=None;self.stop=Event();self.thread=Thread(target=self._run,daemon=True);self.thread.start()
    def _run(self):
        while not self.stop.is_set():
            try:
                with urlopen(Request(self.url,headers={'Authorization':'Bearer '+self._token}),timeout=.35) as r:raw=r.read(262145)
                if len(raw)>262144:raise ValueError('telemetry budget')
                data=json.loads(raw)
                if not data.get('ok'):raise ValueError('telemetry rejected')
                self.latest=(time.monotonic_ns(),data['result']);self.error=None
            except Exception as e:self.error=type(e).__name__
            self.stop.wait(.02)
    def close(self):
        self.stop.set();self.thread.join(1)
        if self.thread.is_alive():raise RuntimeError('read-only telemetry probe did not exit')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);args,ros_args=p.parse_known_args()
    c=json.loads(args.config.read_text())
    if set(c)-{'generation_clock_world'}!={'schema','base_url','target','token_file','directory','source_id','frame_epoch','calibration_version','raw_frames'} or c['schema']!=1:
        raise ValueError('strict owned simulation stream profile required')
    directory=Path(c['directory']);directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    store=StreamStore(directory/'payloads');clock=RosClockBridge();epoch=uuid4().hex
    from vehicle_autonomy.world.sensors.simulation_time import SimulationGenerationClock
    generation=SimulationGenerationClock(c['generation_clock_world']) if 'generation_clock_world' in c else None
    probe=VehicleProbe(c['base_url'],c['target'],c['token_file'])
    # Optional native imports remain confined to this explicitly launched worker.
    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy
    from rclpy.clock import Clock,ClockType
    from rclpy.signals import SignalHandlerOptions
    from sensor_msgs.msg import Image,CameraInfo,LaserScan,PointCloud2,Imu
    from rosgraph_msgs.msg import Clock as RosClock
    from nav_msgs.msg import Odometry
    from geometry_msgs.msg import TransformStamped
    from tf2_ros import TransformBroadcaster,StaticTransformBroadcaster
    stop=False
    def finish(*_):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGTERM,finish);signal.signal(signal.SIGINT,finish)
    rclpy.init(args=ros_args,signal_handler_options=SignalHandlerOptions.NO)
    qos=QoSProfile(depth=2,reliability=ReliabilityPolicy.BEST_EFFORT)
    def ns(stamp):return stamp.sec*1_000_000_000+stamp.nanosec
    def at(value):return TimePoint(value,datetime.now(timezone.utc)-timedelta(microseconds=(time.monotonic_ns()-value)//1000),'host-monotonic-simulation')
    class Streams(Node):
        def __init__(self):
            super().__init__('vaf_world_streams',parameter_overrides=[Parameter('use_sim_time',value=True)])
            self.pending={key:deque(maxlen=8 if key=='scan' else 2) for key in ('camera','scan','cloud','imu')};self.latest={};self.counts={};self.drops={};self.last_source={};self.enqueued_stamp={};self.last_pose=None;self.fault=None;self.frame_epoch=None;self.last_clock=None;self.intrinsics=None;self.scan_wait=None;self.last_tf_ros=None
            self.tf=TransformBroadcaster(self);self.static=StaticTransformBroadcaster(self)
            self.odom=self.create_publisher(Odometry,'/odom',qos)
            self.scan=self.create_publisher(LaserScan,'/scan',qos)
            self.create_subscription(RosClock,'/clock',self.on_clock,qos)
            for cls,topic,key in ((Image,'/phase5/camera/image_raw','camera'),(LaserScan,'/phase5/scan_raw','scan'),(PointCloud2,'/phase5/points','cloud'),(Imu,'/phase5/imu','imu')):
                self.create_subscription(cls,topic,lambda m,k=key:self.enqueue(k,m),qos)
            self.create_subscription(CameraInfo,'/phase5/camera/info',self.on_info,qos)
            self.publish_static()
            self.create_timer(.01,self.tick,clock=Clock(clock_type=ClockType.STEADY_TIME))
            self.create_timer(1.,self.publish_static,clock=Clock(clock_type=ClockType.STEADY_TIME))
        def publish_static(self):
            frames=[('laser',(0.,0.,.2),(0.,0.,0.,1.)),('lidar3d',(0.,0.,.25),(0.,0.,0.,1.)),('imu_frd',(0.,0.,0.),(1.,0.,0.,0.)),
                    ('camera_link',(.15,0.,.25),(0.,0.,0.,1.)),('camera_optical',(0.,0.,0.),(-.5,.5,-.5,.5))]
            transforms=[]
            for name,xyz,xyzw in frames:
                t=TransformStamped();t.header.frame_id='camera_link' if name=='camera_optical' else 'base_link';t.child_frame_id=name
                t.transform.translation.x,t.transform.translation.y,t.transform.translation.z=xyz
                t.transform.rotation.x,t.transform.rotation.y,t.transform.rotation.z,t.transform.rotation.w=xyzw
                transforms.append(t)
            # TRANSIENT_LOCAL retains the complete calibrated tree in one sample.
            # DDS authentication may finish after the first publications.
            self.static.sendTransform(transforms)
        def on_clock(self,message):
            if clock.observe(ns(message.clock),time.monotonic_ns()):self.fault='simulation clock epoch changed; restart and readmit streams'
            self.last_clock=clock.pairs[-1][1] if clock.pairs else None
        def on_info(self,m):
            if m.header.frame_id in c['raw_frames']['camera'] and m.width<=1920 and m.height<=1080 and m.k[0]>0 and m.k[4]>0 and all(math.isfinite(v) for v in (*m.k,*m.d)):
                self.intrinsics=dict(width=m.width,height=m.height,k=list(m.k),d=list(m.d),source_stamp_ns=ns(m.header.stamp),frame=m.header.frame_id)
        def enqueue(self,key,m):
            if m.header.frame_id not in c['raw_frames'][key]:self.drops[key]=self.drops.get(key,0)+1;return
            stamp=ns(m.header.stamp)
            if key=='imu' and stamp-self.enqueued_stamp.get(key,-10_000_000)<10_000_000:
                self.drops[key]=self.drops.get(key,0)+1;return
            self.enqueued_stamp[key]=stamp
            q=self.pending[key]
            if len(q)==q.maxlen:self.drops[key]=self.drops.get(key,0)+1
            q.append((m,time.monotonic_ns()))
        def publish_odom(self,value):
            world=value.get('world');v=None if world is None else world['vehicle']
            if not(value.get('owned_simulation') and value.get('connected') and value.get('signing_configured') and value.get('verified_frames',0)>0 and v and v['health']['quality']=='VALID'):
                raise ValueError('owned authenticated AP state unavailable')
            generation=world['version']['generation_id']
            if self.frame_epoch is None:self.frame_epoch=generation
            if self.frame_epoch!=generation:raise ValueError('AP origin epoch changed; restart and readmit')
            pose=v['reported_pose'];twist=v['reported_twist']
            if not pose or not twist or pose['frame_id']!='odom' or twist['frame_id']!='odom':raise ValueError('AP odom state unavailable')
            capture=pose['captured_at'];now=time.monotonic_ns()
            if capture['clock_domain_id']!='host-monotonic-simulation' or not 0<=now-capture['monotonic_ns']<=500_000_000:raise ValueError('AP odometry expired')
            if self.last_pose==capture['monotonic_ns']:return
            ros=clock.to_ros(capture['monotonic_ns']);msg=Odometry();msg.header.frame_id='odom';msg.child_frame_id='base_link';msg.header.stamp.sec,msg.header.stamp.nanosec=divmod(ros,1_000_000_000)
            pp=pose['value']['position'];qq=pose['value']['orientation'];linear=twist['value']['linear'];angular=twist['value']['angular']
            msg.pose.pose.position.x,msg.pose.pose.position.y,msg.pose.pose.position.z=(float(pp[k]) for k in ('x','y','z'))
            for k in ('x','y','z','w'):setattr(msg.pose.pose.orientation,k,float(qq[k]))
            # AP reports odom ENU twist; Odometry twist is in child base_link FLU.
            yaw=math.atan2(2*(qq['w']*qq['z']+qq['x']*qq['y']),1-2*(qq['y']**2+qq['z']**2))
            msg.twist.twist.linear.x=math.cos(yaw)*linear['x']+math.sin(yaw)*linear['y'];msg.twist.twist.linear.y=-math.sin(yaw)*linear['x']+math.cos(yaw)*linear['y'];msg.twist.twist.linear.z=linear['z'];msg.twist.twist.angular.z=angular['z']
            t=TransformStamped();t.header=msg.header;t.child_frame_id='base_link';t.transform.translation.x,t.transform.translation.y,t.transform.translation.z=msg.pose.pose.position.x,msg.pose.pose.position.y,msg.pose.pose.position.z;t.transform.rotation=msg.pose.pose.orientation
            self.odom.publish(msg);self.tf.sendTransform(t);self.last_tf_ros=ros;self.last_pose=capture['monotonic_ns'];self.counts['odom']=self.counts.get('odom',0)+1
        def consume(self,key,m,received,capture):
            frame={'camera':('camera_optical','camera_optical'),'scan':('laser','FLU'),'cloud':('lidar3d','FLU'),'imu':('imu_frd','FRD')}[key]
            kind={'camera':DataKind.IMAGE,'scan':DataKind.SCAN,'cloud':DataKind.CLOUD,'imu':DataKind.IMU}[key]
            seq=self.counts.get(key,0)+1
            dimensions=()
            if key=='camera':
                if m.encoding not in ('rgb8','bgr8') or not(0<m.width<=1920 and 0<m.height<=1080 and m.step==m.width*3 and len(m.data)==m.step*m.height):raise ValueError('unsupported image layout')
                payload=bytes(m.data);media='application/x-raw-'+m.encoding;dimensions=(m.height,m.width,3)
            elif key=='cloud':
                if m.width*m.height>200000 or m.row_step*m.height!=len(m.data) or len(m.data)>8*1024*1024:raise ValueError('cloud budget/layout')
                from rclpy.serialization import serialize_message
                payload=serialize_message(m);media='application/vnd.ros.cdr;type=sensor_msgs/msg/PointCloud2';dimensions=(m.height,m.width)
            elif key=='scan':
                if not 1<=len(m.ranges)<=4096:raise ValueError('scan budget')
                payload=json.dumps(dict(angle_min=float(m.angle_min),angle_increment=float(m.angle_increment),range_min=float(m.range_min),range_max=float(m.range_max),ranges=[float(v) if math.isfinite(v) else None for v in m.ranges]),allow_nan=False).encode();media='application/vnd.ros.laserscan'
                # Raw calibrated scan is independent of AP odometry arrival.
                # Keep the original sample stamp. Native TF/message filters and
                # the separate navigation pose/transform guards do the matching.
                relay=copy.deepcopy(m);relay.header.frame_id='laser';self.scan.publish(relay);self.scan_wait=None
            else:
                payload=json.dumps(dict(orientation=[m.orientation.x,m.orientation.y,m.orientation.z,m.orientation.w],angular_velocity=[m.angular_velocity.x,m.angular_velocity.y,m.angular_velocity.z],linear_acceleration=[m.linear_acceleration.x,m.linear_acceleration.y,m.linear_acceleration.z]),allow_nan=False).encode();media='application/vnd.ros.imu'
            ref=store.put(payload,media,dimensions,channel=key)
            header=SampleHeader(c['source_id'],key,kind,epoch,seq,ns(m.header.stamp),'ros-simulation:'+clock.epoch,at(received),at(capture),FrameDescriptor(frame[0],frame[1],c['frame_epoch']),c['calibration_version'],SourceKind.SIMULATION,QualityState.VALID)
            self.latest[key]=to_json_value(StreamObservation(header,ref));self.counts[key]=seq
            if key=='cloud':self.latest[key]['layout']=dict(fields=[dict(name=f.name,offset=f.offset,datatype=f.datatype,count=f.count) for f in m.fields],point_step=m.point_step,row_step=m.row_step,is_bigendian=m.is_bigendian)
        def tick(self):
            error=self.fault;odom_error=None
            try:
                if error:raise ValueError(error)
                now=time.monotonic_ns()
                if self.last_clock is None or now-self.last_clock>500_000_000:raise ValueError('clock unavailable/paused')
                try:
                    if probe.latest is None or now-probe.latest[0]>500_000_000:raise ValueError('AP probe stale')
                    self.publish_odom(probe.latest[1])
                except (ValueError,LookupError) as exc:odom_error=str(exc)
                for key,q in self.pending.items():
                    while q:
                        m,received=q[0]
                        if now-received>500_000_000:q.popleft();self.drops[key]=self.drops.get(key,0)+1;continue
                        source=ns(m.header.stamp)
                        if source<=self.last_source.get(key,-1):q.popleft();self.drops[key]=self.drops.get(key,0)+1;continue
                        try:
                            capture=generation.lower_bound(source,at(now),strict_previous=True).monotonic_ns if generation else clock.to_host(source)
                            if capture>received:
                                if capture-received>20_000_000:raise ValueError('capture follows receipt')
                                capture=received # Conservative older capture for delivery-order ambiguity.
                            if now-capture>500_000_000:raise ValueError('source sample expired')
                            self.consume(key,m,received,capture)
                        except LookupError:break
                        except ValueError:q.popleft();self.drops[key]=self.drops.get(key,0)+1;continue
                        q.popleft();self.last_source[key]=source
            except (ValueError,LookupError) as exc:error=str(exc)
            atomic_json(directory/'state.json',dict(schema=1,generation=epoch,source_kind='simulation',source_id=c['source_id'],origin_id=c['frame_epoch'],ap_world_epoch=self.frame_epoch,published_ns=time.monotonic_ns(),error=error,odom_error=odom_error,streams=self.latest,intrinsics=self.intrinsics,counts=self.counts,dropped=self.drops,queue_depths={k:len(v) for k,v in self.pending.items()},dropped_scope='worker reference processing only; raw ROS topics unmodified',scan_wait=self.scan_wait,last_tf_ros=self.last_tf_ros,generation_clock=None if generation is None else dict(fault=generation.fault,samples=len(generation.samples))))
    node=Streams()
    try:
        while rclpy.ok() and not stop:rclpy.spin_once(node,timeout_sec=.05)
    finally:
        probe.close()
        if generation:generation.close()
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
        atomic_json(directory/'stopped.json',dict(stopped=True,generation=epoch,at_ns=time.monotonic_ns()))


if __name__=='__main__':main()
