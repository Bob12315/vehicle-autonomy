"""SLAM sidecar: App telemetry -> odometry TF; ROS maps -> read-only resources.

No vehicle command subscription exists. All movement belongs to the existing
Application/Mission/Execution path. ROS imports are deliberately inside main.
"""
from __future__ import annotations

import argparse
from collections import deque
import copy
import json
import math
from pathlib import Path
import threading
import time
from uuid import uuid4

from app.control import request
from mapping.clock import RosClockBridge
from mapping.exchange import MappingConfig
from mapping.grid import MapStore, OccupancyGrid, atomic_json, pose_from_json, pose_to_json


class ApplicationProbe:
    """A slow IPC peer cannot block the ROS executor or the vehicle process."""
    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.latest = None
        self.error = None
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self.closed.is_set():
            try:
                response = request(self.socket_path, "status", timeout_s=.35)
                if not response["ok"]:
                    raise ValueError(response.get("error", "application status rejected"))
                self.latest = (time.monotonic_ns(), response["result"])
                self.error = None
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.error = str(exc)
            self.closed.wait(.08)

    def close(self):
        self.closed.set()
        self.thread.join(timeout=1)
        if self.thread.is_alive():
            raise RuntimeError("application status worker did not stop")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--control-socket", required=True)
    parser.add_argument("--clock-domain", default="host-monotonic-simulation")
    args, ros_args = parser.parse_known_args()
    config = MappingConfig.load(args.config, args.clock_domain)
    config.directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.qos import qos_profile_sensor_data, QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from rclpy.time import Time
    from geometry_msgs.msg import TransformStamped
    from nav_msgs.msg import OccupancyGrid as RosOccupancyGrid
    from rosgraph_msgs.msg import Clock
    from sensor_msgs.msg import LaserScan
    from tf2_ros import Buffer, TransformListener, TransformBroadcaster, StaticTransformBroadcaster

    def ns(stamp):
        return stamp.sec * 1_000_000_000 + stamp.nanosec

    def set_stamp(stamp, value):
        stamp.sec, stamp.nanosec = divmod(value, 1_000_000_000)

    def transform_pose(transform):
        t, q = transform.transform.translation, transform.transform.rotation
        return pose_from_json({"position": [t.x, t.y, t.z], "orientation": [q.x, q.y, q.z, q.w]})

    class MappingNode(Node):
        def __init__(self):
            super().__init__("vaf_mapping_bridge", parameter_overrides=[Parameter("use_sim_time", value=True)])
            self.clock_mapper = RosClockBridge()
            self.source_epoch = uuid4().hex
            self.frame_epoch = None
            self.epoch_error = None
            self.probe = ApplicationProbe(args.control_socket)
            self.buffer = Buffer(node=self)
            self.listener = TransformListener(self.buffer, self)
            self.broadcaster = TransformBroadcaster(self)
            self.static_broadcaster = StaticTransformBroadcaster(self)
            self.store = MapStore(config.directory / "maps")
            self.revision = 0
            self.pending = None
            self.last_valid = None
            self.last_tf_stamp = None
            self.last_clock_host = None
            self.scans = 0
            self.pending_scans = deque(maxlen=16)
            self.odom_updates = 0
            self.map_updates = 0
            self.map_publisher = None
            self.last_scan_ros = None
            self.scan_drop = None
            self.last_diagnostic = 0
            self.scan_pub = self.create_publisher(LaserScan, "/scan", qos_profile_sensor_data)
            self.create_subscription(Clock, "/clock", self.on_clock, qos_profile_sensor_data)
            self.create_subscription(LaserScan, "/scan_raw", self.on_scan, qos_profile_sensor_data)
            map_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                 durability=DurabilityPolicy.TRANSIENT_LOCAL)
            self.create_subscription(RosOccupancyGrid, "/map", self.on_map, map_qos)
            static = TransformStamped()
            static.header.frame_id, static.child_frame_id = "base_link", "laser"
            static.transform.translation.z = .2
            static.transform.rotation.w = 1.
            self.laser_transform = static
            self.static_broadcaster.sendTransform(static)
            self.timer = self.create_timer(.05, self.tick, clock=rclpy.clock.Clock(clock_type=rclpy.clock.ClockType.STEADY_TIME))

        def on_clock(self, message):
            host = time.monotonic_ns()
            if self.clock_mapper.observe(ns(message.clock), host):
                self.pending = self.last_valid = None
                self.pending_scans.clear()
                self.source_epoch = uuid4().hex
                self.revision = 0
                self.last_tf_stamp = None
                self.buffer.clear()
                self.static_broadcaster.sendTransform(self.laser_transform)
            self.last_clock_host = self.clock_mapper.pairs[-1][1] if self.clock_mapper.pairs else None

        def on_scan(self, message):
            self.last_scan_ros = ns(message.header.stamp)
            if len(message.ranges) <= 4096:
                self.pending_scans.append((message, time.monotonic_ns()))

        def flush_scans(self):
            # Independent /clock, scan and telemetry streams can arrive in any
            # order. Wait for bracketing data instead of extrapolating TF/time.
            while self.pending_scans:
                message, received = self.pending_scans[0]
                stamp = ns(message.header.stamp)
                if time.monotonic_ns() - received > 750_000_000:
                    self.pending_scans.popleft()
                    self.scan_drop = "scan exceeded the bounded synchronization wait"
                    continue
                try:
                    capture = self.clock_mapper.to_host(stamp)
                except LookupError:
                    self.scan_drop = "waiting for bracketing clock samples"
                    break
                if self.last_tf_stamp is None or stamp > self.last_tf_stamp or not self.buffer.can_transform("odom", "laser", Time.from_msg(message.header.stamp)):
                    self.scan_drop = "waiting for time-matched telemetry TF"
                    break
                self.pending_scans.popleft()
                if not 0 <= time.monotonic_ns() - capture <= 750_000_000:
                    self.scan_drop = "scan capture expired"
                    continue
                relay = copy.deepcopy(message)
                relay.header.frame_id = "laser"
                self.scan_pub.publish(relay)
                self.scans += 1
                self.scan_drop = None

        def on_map(self, message):
            # Jazzy's message-info dictionary does not expose publisher GID.
            # A single explicitly scoped map authority is required instead.
            publishers = self.get_publishers_info_by_topic("/map")
            if len(publishers) != 1:
                self.pending = self.last_valid = None
                return
            publisher = bytes(publishers[0].endpoint_gid)
            if self.map_publisher is not None and publisher != self.map_publisher:
                self.pending = self.last_valid = None
                self.source_epoch = uuid4().hex
                self.revision = 0
                self.last_tf_stamp = None
                self.buffer.clear()
                self.static_broadcaster.sendTransform(self.laser_transform)
            self.map_publisher = publisher
            self.pending = (message, time.monotonic_ns())

        def envelope(self, status, error=None):
            return {"schema": 1, "source": "ros2.slam_toolbox", "source_epoch": self.source_epoch,
                "frame_epoch": self.frame_epoch, "clock_domain_id": args.clock_domain,
                "published_ns": time.monotonic_ns(), "status": status, "error": error,
                "counts": {"scans": self.scans, "odometry": self.odom_updates, "maps": self.map_updates},
                "timing": {"clock_ros_ns": None if not self.clock_mapper.pairs else self.clock_mapper.pairs[-1][0],
                           "last_tf_ros_ns": self.last_tf_stamp, "last_scan_ros_ns": self.last_scan_ros,
                           "scan_drop": self.scan_drop}}

        def publish_odometry(self, status):
            pose = status["vehicle"]["pose"]
            if pose is None or pose["frame"] != "odom" or not 0 <= time.monotonic_ns()-pose["captured_ns"] <= 750_000_000:
                raise ValueError("fresh telemetry pose in odom required")
            stamp = self.clock_mapper.to_ros(pose["captured_ns"])
            if self.last_tf_stamp is not None and stamp <= self.last_tf_stamp:
                return
            validated = pose_from_json({"position": pose["position"], "orientation": pose["orientation_xyzw"]})
            transform = TransformStamped()
            transform.header.frame_id, transform.child_frame_id = "odom", "base_link"
            set_stamp(transform.header.stamp, stamp)
            p, q = validated.position, validated.orientation
            transform.transform.translation.x, transform.transform.translation.y, transform.transform.translation.z = p.x, p.y, p.z
            transform.transform.rotation.x, transform.transform.rotation.y = q.x, q.y
            transform.transform.rotation.z, transform.transform.rotation.w = q.z, q.w
            self.broadcaster.sendTransform(transform)
            self.static_broadcaster.sendTransform(self.laser_transform)
            self.last_tf_stamp = stamp
            self.odom_updates += 1

        def adopt_map(self):
            message, received = self.pending
            if message.header.frame_id != "map":
                raise ValueError("SLAM must publish its explicit map frame")
            capture = self.clock_mapper.to_host(ns(message.header.stamp))
            # Clock pairs are reception observations, not hardware synchronization.
            # A <=20 ms delivery-order ambiguity may only make capture older.
            if capture > received:
                if capture - received > 20_000_000:
                    raise ValueError("map time follows receive time")
                capture = received
            if time.monotonic_ns() - capture > config.max_age_ns:
                raise ValueError("SLAM map expired before adoption")
            at = Time.from_msg(message.header.stamp)
            base = transform_pose(self.buffer.lookup_transform("map", "base_link", at))
            odom = transform_pose(self.buffer.lookup_transform("map", "odom", at))
            o = message.info.origin
            origin = pose_from_json({"position": [o.position.x, o.position.y, o.position.z],
                "orientation": [o.orientation.x, o.orientation.y, o.orientation.z, o.orientation.w]})
            grid = OccupancyGrid("map", float(message.info.resolution), message.info.width, message.info.height,
                                 origin, tuple(int(v) for v in message.data))
            digest = self.store.save(grid)
            self.revision += 1
            self.map_updates += 1
            value = self.envelope("VALID")
            value.update({"map": {"revision": self.revision, "sha256": digest, "captured_ns": capture},
                          "base_link_in_map": pose_to_json(base), "odom_in_map": pose_to_json(odom)})
            self.last_valid = value
            self.pending = None
            self.get_logger().info(f"map revision={self.revision} size={grid.width}x{grid.height} scans={self.scans}")

        def tick(self):
            try:
                now = time.monotonic_ns()
                if self.probe.latest is None or now - self.probe.latest[0] > 750_000_000:
                    raise ValueError("application status unavailable or stale")
                status = self.probe.latest[1]
                if not status["connected"] or status["vehicle"] is None or status["world_version"] is None:
                    raise ValueError("application has no fresh vehicle session")
                if status["clock_domain_id"] != args.clock_domain:
                    raise ValueError("application clock domain mismatch")
                epoch = status["world_version"]["generation"]
                if self.frame_epoch is None:
                    self.frame_epoch = epoch
                elif epoch != self.frame_epoch:
                    self.epoch_error = "application frame epoch changed; restart ROS mapping stack"
                if self.epoch_error:
                    raise ValueError(self.epoch_error)
                if self.last_clock_host is None or now - self.last_clock_host > 750_000_000:
                    raise ValueError("ROS clock unavailable or paused")
                self.publish_odometry(status)
                self.flush_scans()
                if self.pending is not None:
                    self.adopt_map()
                if self.last_valid is None:
                    raise ValueError("waiting for SLAM map and time-matched transforms")
                value = {**self.last_valid, "published_ns": now}
                if now - value["map"]["captured_ns"] > config.max_age_ns:
                    raise ValueError("SLAM map expired")
            except Exception as exc:
                value = self.envelope("UNAVAILABLE", f"{type(exc).__name__}: {exc}")
            if now - self.last_diagnostic > 5_000_000_000:
                self.get_logger().info(json.dumps({"status": value["status"], "error": value.get("error"),
                    "counts": value["counts"], "timing": value.get("timing"),
                    "frames": self.buffer.all_frames_as_yaml()}))
                self.last_diagnostic = now
            atomic_json(config.directory / "bridge.json", value)

        def close(self):
            atomic_json(config.directory / "bridge.json", self.envelope("UNAVAILABLE", "ROS mapping bridge stopped"))
            self.probe.close()

    rclpy.init(args=ros_args)
    node = MappingNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    except RuntimeError:
        # SIGTERM can invalidate the context while spin constructs a wait set.
        # Suppress only this shutdown race; runtime ROS failures still propagate.
        if rclpy.ok():
            raise
    finally:
        node.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
