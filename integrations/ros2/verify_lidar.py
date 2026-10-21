"""Finite receive-only PointCloud2/LaserScan acceptance against a fresh SDK exchange."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exchange', required=True, type=Path)
    parser.add_argument('--provenance', required=True, choices=('live_sdk_system_timestamp', 'pcap_replay'))
    parser.add_argument('--duration', type=float, default=20)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    if not 3 <= args.duration <= 120:
        parser.error('duration must be 3..120 seconds')
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import PointCloud2, LaserScan
    from sensor_msgs_py import point_cloud2
    from sensors.lidar.exchange import load_exchange
    rclpy.init(); node = Node('vaf_lidar_acceptance')
    counts = {'points': 0, 'scan': 0}; errors = []; stamps = {}; epochs = set()
    point_counts = []; known_bins = []; ages = []; source_sequences = set(); publishers = {}

    def consume(message, kind):
        try:
            stamp = message.header.stamp.sec*1_000_000_000+message.header.stamp.nanosec
            age = node.get_clock().now().nanoseconds-stamp
            if message.header.frame_id != 'lidar' or not 0 <= age <= 500_000_000:
                raise ValueError('frame or source timestamp rejected')
            if kind in stamps and stamp <= stamps[kind]:
                raise ValueError('duplicate/regressed ROS timestamp')
            stamps[kind] = stamp; ages.append(age)
            if kind == 'points':
                points = list(point_cloud2.read_points(message, field_names=('x','y','z'), skip_nans=False))
                if not 1 <= len(points) <= 200000 or not all(math.isfinite(float(v)) for p in points for v in p):
                    raise ValueError('point budget or finite XYZ rejected')
                point_counts.append(len(points))
            else:
                valid = [r for r in message.ranges if math.isfinite(r)]
                if len(message.ranges) != 720 or not valid or not all(message.range_min <= r <= message.range_max for r in valid):
                    raise ValueError('scan shape/range/coverage rejected')
                known_bins.append(len(valid))
            counts[kind] += 1
        except ValueError as exc:
            errors.append(f'{kind}: {exc}')

    subscriptions = [node.create_subscription(PointCloud2, '/vaf/lidar/points',
        lambda msg: consume(msg, 'points'), qos_profile_sensor_data),
        node.create_subscription(LaserScan, '/vaf/lidar/scan',
        lambda msg: consume(msg, 'scan'), qos_profile_sensor_data)]
    start = time.monotonic()
    try:
        while time.monotonic()-start < args.duration:
            rclpy.spin_once(node, timeout_sec=.05)
            try:
                value = load_exchange(args.exchange, time.monotonic_ns())
                if value['provenance'] != args.provenance:
                    raise ValueError('SDK provenance differs from requested acceptance source')
                epochs.add(value['epoch']); source_sequences.add(value['sequence'])
            except (ValueError, OSError) as exc:
                errors.append('exchange: '+str(exc))
        for topic in ('/vaf/lidar/points', '/vaf/lidar/scan'):
            publishers[topic] = [p.node_name for p in node.get_publishers_info_by_topic(topic)]
        passed = (not errors and len(epochs) == 1 and len(source_sequences) >= 5
                  and min(counts.values()) >= max(5, int(args.duration*2))
                  and all(names == ['vaf_rs16_scan'] for names in publishers.values()))
        result = {'passed': passed, 'provenance': args.provenance, 'duration_s': time.monotonic()-start,
                  'counts': counts, 'rates_hz': {k:v/args.duration for k,v in counts.items()},
                  'point_count_range': [min(point_counts),max(point_counts)] if point_counts else None,
                  'known_scan_bins_range': [min(known_bins),max(known_bins)] if known_bins else None,
                  'maximum_ros_source_age_ms': max(ages)/1e6 if ages else None,
                  'source_epochs': sorted(epochs), 'unique_source_sequences':len(source_sequences),
                  'publishers': publishers, 'errors':errors[:50], 'error_count':len(errors),
                  'control_eligible': False, 'physical_mount_and_stop_acceptance': 'NOT_TESTED'}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2)); print(json.dumps(result))
    finally:
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
