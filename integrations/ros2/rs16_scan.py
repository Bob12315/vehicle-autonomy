"""Optional ROS2 SDK PointCloud2 -> typed Observation -> LaserScan sidecar."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from uuid import uuid4

from contracts.core.time import TimePoint
from sensors.lidar.scan import ScanConfig, ScanProcessor


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topic',default='/rslidar_points')
    parser.add_argument('--scan-topic',default='/vaf/lidar/scan')
    parser.add_argument('--config',required=True)
    parser.add_argument('--health-file',type=Path,required=True)
    parser.add_argument('--exchange',type=Path,help='same-host official native SDK exchange; publishes PointCloud2')
    parser.add_argument('--self-test',action='store_true',help='explicit synthetic ROS software fixture, never hardware evidence')
    args=parser.parse_args()
    config=ScanConfig(**json.loads(Path(args.config).read_text()))
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import LaserScan, PointCloud2
    from sensor_msgs_py import point_cloud2
    from std_msgs.msg import Header
    rclpy.init()
    node=Node('vaf_rs16_scan')
    domain=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    processor=ScanProcessor(config,'robosense.ros2',uuid4().hex)
    publisher=node.create_publisher(LaserScan,args.scan_topic,qos_profile_sensor_data)
    cloud_pub=node.create_publisher(PointCloud2,'/vaf/lidar/points',qos_profile_sensor_data) if args.exchange else None
    count=0
    last_exchange=None
    rejected=0
    observed=[]

    def write_health(error=None):
        now=TimePoint(time.monotonic_ns(),datetime.now(timezone.utc),domain)
        health={**processor.health(now),'scope':'synthetic_ros_software_fixture' if args.self_test else 'SDK ROS input; mount/time unqualified',
                'control_eligible':False,'rejected':rejected}
        if error:health.update(error=error,online=False)
        temporary=args.health_file.with_suffix('.tmp')
        temporary.write_text(json.dumps(health));temporary.replace(args.health_file)

    def consume(message, *, raw=None):
        nonlocal count,rejected
        count+=1
        received=time.monotonic_ns()
        capture=(received-(time.time_ns()-(message.header.stamp.sec*1_000_000_000+message.header.stamp.nanosec))) if raw is None else raw['capture_ns']
        try:
            points=(tuple(float(v) for v in p) for p in point_cloud2.read_points(message,field_names=('x','y','z'),skip_nans=False))
            observation=processor.convert(points,frame=message.header.frame_id,
                sequence=count if raw is None else raw['sequence'],
                captured_at=TimePoint(capture,datetime.now(timezone.utc),domain),
                received_at=TimePoint(received,datetime.now(timezone.utc),domain),epoch=processor.epoch)
            scan=LaserScan();scan.header=message.header
            data=observation.data
            scan.angle_min=data.angle_min;scan.angle_increment=data.angle_increment
            scan.angle_max=data.angle_min+(len(data.ranges)-1)*data.angle_increment
            scan.range_min=data.range_min;scan.range_max=data.range_max
            scan.ranges=[math.nan if r is None else r for r in data.ranges]
            publisher.publish(scan)
            observed.append(min(r for r in data.ranges if r is not None))
            del observed[:-20]
            write_health()
        except (ValueError,TypeError,OverflowError) as exc:
            rejected+=1;write_health(str(exc))

    subscriber=node.create_subscription(PointCloud2,args.topic,consume,qos_profile_sensor_data)

    def poll_exchange():
        nonlocal last_exchange,rejected
        try:
            from sensors.lidar.exchange import load_exchange
            raw=load_exchange(args.exchange,time.monotonic_ns())
            key=raw['epoch'],raw['sequence']
            if key==last_exchange:
                return
            if last_exchange is not None and raw['epoch']!=last_exchange[0]:
                raise ValueError('SDK epoch changed; restart sidecar and re-admit')
            last_exchange=key
            header=Header();header.frame_id=raw['frame']
            seconds=raw['source_timestamp_s'];header.stamp.sec=int(seconds)
            header.stamp.nanosec=int((seconds-int(seconds))*1e9)
            message=point_cloud2.create_cloud_xyz32(header,raw['points'])
            cloud_pub.publish(message)
            consume(message,raw=raw)
        except (ValueError,OSError,KeyError) as exc:
            rejected+=1;write_health(str(exc))

    timer=node.create_timer(.05,poll_exchange) if args.exchange else None
    try:
        if args.self_test:
            test_pub=node.create_publisher(PointCloud2,args.topic,qos_profile_sensor_data)
            start=time.monotonic()
            while time.monotonic()-start<2:
                rclpy.spin_once(node,timeout_sec=.05)
            for i in range(8):
                header=Header();header.frame_id='wrong' if i==5 else config.frame
                header.stamp=node.get_clock().now().to_msg()
                if i==6:header.stamp.sec-=5
                points=[(math.cos(j*2*math.pi/720),math.sin(j*2*math.pi/720),0.) for j in range(720)]
                test_pub.publish(point_cloud2.create_cloud_xyz32(header,points))
                until=time.monotonic()+.2
                while time.monotonic()<until:rclpy.spin_once(node,timeout_sec=.02)
            assert processor.accepted>=5 and rejected>=2 and all(abs(x-1.)<1e-5 for x in observed)
            print(json.dumps({'passed':True,'accepted':processor.accepted,'rejected':rejected,
                              'scope':'synthetic PointCloud2 ROS software chain, not real RS16 or PCAP'}))
        else:
            while rclpy.ok():
                rclpy.spin_once(node,timeout_sec=.1)
                if processor.last_received is not None:write_health()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node();rclpy.shutdown()
    return 0


if __name__=='__main__':raise SystemExit(main())
