"""Explicit Gazebo→ROS simulation worker; no hardware or vehicle command ports."""
import argparse
from collections import deque
import json
from pathlib import Path
import signal
from threading import Lock
import time

from .mid360_data import convert, FIELDS, POINT_STEP, fresh
from vehicle_autonomy.world.sensors.camera.live import atomic
from vehicle_autonomy.world.sensors.camera.gazebo import clock_pair, fresh_capture


def run(config, directory):
    # All optional dependencies remain inside the launched worker.
    import rclpy
    from rclpy.node import Node as RosNode
    from rclpy.parameter import Parameter
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, qos_profile_sensor_data
    from builtin_interfaces.msg import Time
    from geometry_msgs.msg import TransformStamped, PoseStamped
    from nav_msgs.msg import Path as RosPath
    from sensor_msgs.msg import PointCloud2, PointField, Imu
    from std_msgs.msg import String
    from tf2_msgs.msg import TFMessage
    from rosgraph_msgs.msg import Clock as RosClock
    from gz.transport13 import Node
    from gz.msgs10.clock_pb2 import Clock
    from gz.msgs10.pointcloud_packed_pb2 import PointCloudPacked
    from gz.msgs10.imu_pb2 import IMU
    from gz.msgs10.pose_v_pb2 import Pose_V
    import math

    if config['source'] != 'gazebo-live' or config['kind'] not in ('rover', 'copter'):
        raise ValueError('explicit supported simulation source required')
    rclpy.init(args=[])
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    ns = config['namespace']
    ros = RosNode('vaf_mid360', namespace=ns, parameter_overrides=[Parameter('use_sim_time', value=True)])
    reliable = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
    retained = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                          durability=DurabilityPolicy.TRANSIENT_LOCAL)
    points = ros.create_publisher(PointCloud2, ns+'/points', qos_profile_sensor_data)
    imu_pub = ros.create_publisher(Imu, ns+'/imu', qos_profile_sensor_data)
    clock_pub = ros.create_publisher(RosClock, '/clock', reliable)
    tf = ros.create_publisher(TFMessage, ns+'/tf', reliable)
    tf_static = ros.create_publisher(TFMessage, ns+'/tf_static', retained)
    path_pub = ros.create_publisher(RosPath, ns+'/trajectory', reliable)
    description = ros.create_publisher(String, ns+'/robot_description', retained)
    status = ros.create_publisher(String, ns+'/status', reliable)
    lock = Lock()
    queues = {k: deque(maxlen=n) for k, n in [('clock', 1), ('points', 1), ('imu', 400), ('pose', 200)]}
    def receive(kind):
        def callback(message):
            with lock:
                queues[kind].append((message, time.monotonic_ns(), time.time_ns()))
        return callback
    transport = Node()
    subscriptions = [(Clock, '/world/'+config['world']+'/clock', 'clock'),
        (PointCloudPacked, config['points_gz'], 'points'), (IMU, config['imu_gz'], 'imu'),
        (Pose_V, '/world/'+config['world']+'/pose/info', 'pose')]
    for kind, topic, key in subscriptions:
        if not transport.subscribe(kind, topic, receive(key)):
            raise RuntimeError('Gazebo subscription failed: '+topic)

    def stamp(ns):
        result = Time()
        result.sec, result.nanosec = divmod(ns, 1_000_000_000)
        return result
    def transform(parent, child, xyz, q, when):
        result = TransformStamped()
        result.header.frame_id, result.child_frame_id, result.header.stamp = parent, child, stamp(when)
        result.transform.translation.x, result.transform.translation.y, result.transform.translation.z = map(float, xyz)
        result.transform.rotation.x, result.transform.rotation.y, result.transform.rotation.z, result.transform.rotation.w = map(float, q)
        return result
    def static(when):
        roll, pitch, yaw = config['mount'][3:]
        cr, cp, cy = math.cos(roll/2), math.cos(pitch/2), math.cos(yaw/2)
        sr, sp, sy = math.sin(roll/2), math.sin(pitch/2), math.sin(yaw/2)
        q = [sr*cp*cy-cr*sp*sy, cr*sp*cy+sr*cp*sy, cr*cp*sy-sr*sp*cy, cr*cp*cy+sr*sp*sy]
        tf_static.publish(TFMessage(transforms=[
            transform(config['model_frame'], config['base_frame'], config['model_to_body'], [0,0,0,1], when),
            transform(config['base_frame'], config['lidar_frame'], config['mount'][:3], q, when)]))
        description.publish(String(data=robot_description(config)))
    def clear(when):
        msg = PointCloud2()
        msg.header.frame_id, msg.header.stamp = config['lidar_frame'], stamp(max(0, when))
        msg.height, msg.point_step = 1, POINT_STEP
        msg.fields = [PointField(name=n, offset=o, datatype=d, count=1) for n,o,d in FIELDS]
        points.publish(msg)
        trajectory.poses.clear()
        trajectory.header.stamp = msg.header.stamp
        path_pub.publish(trajectory)

    pair = None
    latest_pose = last_points = last_imu = None
    last_point_stamp = last_imu_stamp = last_pose_stamp = -1
    last_status = 0.
    last_static = 0.
    sequence = imu_sequence = 0
    fault = None
    invalidated = False
    details = {}
    trajectory = RosPath()
    trajectory.header.frame_id = config['world_frame']
    try:
        while not stopped:
            rclpy.spin_once(ros, timeout_sec=.005)
            now = time.monotonic_ns()
            began=now;timings={}
            with lock:
                batch = {k: list(q) for k,q in queues.items()}
                for q in queues.values():
                    q.clear()
            for clock, received, wall in batch['clock']:
                value = clock.sim.sec*1_000_000_000+clock.sim.nsec
                system = clock.system.sec*1_000_000_000+clock.system.nsec
                try:
                    candidate = clock_pair(value, system, received, wall)
                except ValueError:
                    continue
                if pair is not None and value < pair[0]:
                    # A reset creates a new time epoch: exit instead of joining
                    # data/TF from two epochs or leaving old RViz caches valid.
                    raise RuntimeError('simulation clock regressed; restart sensor with a fresh domain')
                pair = candidate
                clock_pub.publish(RosClock(clock=stamp(value)))
            timings['clock_ms']=(time.monotonic_ns()-began)/1e6;section=time.monotonic_ns()
            for message, received, _ in batch['pose']:
                captured = message.header.stamp.sec*1_000_000_000+message.header.stamp.nsec
                target = next((p for p in message.pose if p.name == config['entity']), None)
                if target is None or captured <= last_pose_stamp or not fresh_capture(pair, captured, now):
                    continue
                pos, q = target.position, target.orientation
                coords = [pos.x,pos.y,pos.z,q.x,q.y,q.z,q.w]
                if not all(math.isfinite(v) for v in coords) or abs(sum(v*v for v in coords[3:])-1) > .01:
                    continue
                last_pose_stamp, latest_pose = captured, received
                t = transform(config['world_frame'], config['model_frame'], coords[:3], coords[3:], captured)
                tf.publish(TFMessage(transforms=[t]))
                if time.monotonic()-last_static > 1.:
                    static(captured)
                    last_static = time.monotonic()
                pose = PoseStamped()
                pose.header = t.header
                pose.pose.position.x, pose.pose.position.y, pose.pose.position.z = coords[:3]
                pose.pose.orientation = t.transform.rotation
                trajectory.header = t.header
                if not trajectory.poses or captured-(trajectory.poses[-1].header.stamp.sec*1_000_000_000+trajectory.poses[-1].header.stamp.nanosec) >= 100_000_000:
                    trajectory.poses.append(pose)
                    trajectory.poses = trajectory.poses[-2000:]
                    path_pub.publish(trajectory)
            timings['pose_ms']=(time.monotonic_ns()-section)/1e6;section=time.monotonic_ns()
            injected = (directory/'fault').is_file()
            for message, received, _ in batch['points']:
                captured = message.header.stamp.sec*1_000_000_000+message.header.stamp.nsec
                if (injected or captured <= last_point_stamp or not fresh(received, now)
                        or not fresh_capture(pair, captured, now) or not fresh(latest_pose, now)):
                    continue
                data, details = convert(message)
                msg = PointCloud2()
                msg.header.frame_id, msg.header.stamp = config['lidar_frame'], stamp(captured)
                msg.height, msg.width, msg.point_step = 1, details['points'], POINT_STEP
                msg.row_step, msg.is_dense, msg.is_bigendian = msg.width*POINT_STEP, True, False
                msg.fields = [PointField(name=n, offset=o, datatype=d, count=1) for n,o,d in FIELDS]
                msg.data = data
                points.publish(msg)
                last_point_stamp, last_points = captured, received
                sequence += 1
            timings['points_ms']=(time.monotonic_ns()-section)/1e6;section=time.monotonic_ns()
            for message, received, _ in batch['imu']:
                captured = message.header.stamp.sec*1_000_000_000+message.header.stamp.nsec
                if injected or captured <= last_imu_stamp or not fresh(received, now) or not fresh_capture(pair,captured,now):
                    continue
                msg = Imu()
                msg.header.frame_id, msg.header.stamp = config['lidar_frame'], stamp(captured)
                msg.orientation_covariance[0] = -1.  # no absolute heading promise
                msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z = message.angular_velocity.x, message.angular_velocity.y, message.angular_velocity.z
                msg.linear_acceleration.x, msg.linear_acceleration.y, msg.linear_acceleration.z = message.linear_acceleration.x, message.linear_acceleration.y, message.linear_acceleration.z
                if not all(math.isfinite(v) for v in (msg.angular_velocity.x,msg.angular_velocity.y,msg.angular_velocity.z,msg.linear_acceleration.x,msg.linear_acceleration.y,msg.linear_acceleration.z)):
                    continue
                imu_pub.publish(msg)
                last_imu_stamp, last_imu = captured, received
                imu_sequence += 1
            timings['imu_ms']=(time.monotonic_ns()-section)/1e6
            timings['loop_ms']=(time.monotonic_ns()-began)/1e6
            now=time.monotonic_ns()
            healthy = not injected and all(fresh(v,now) for v in (last_points,last_imu,latest_pose)) and pair is not None and fresh(pair[1],now)
            fault = None if healthy else 'injected sensor interruption' if injected else 'waiting for fresh cloud, IMU, pose and clock'
            if not healthy and not invalidated:
                clear(pair[0] if pair else 0)
                invalidated = True
            if healthy:
                invalidated = False
            if time.monotonic()-last_status > .25:
                last_status = time.monotonic()
                health = dict(source='gazebo-live', backend=config['backend'], online=healthy,
                    error=fault, sequence=sequence, imu_sequence=imu_sequence, received_ns=now,
                    points_age_ns=None if last_points is None else now-last_points,
                    imu_age_ns=None if last_imu is None else now-last_imu,
                    clock_ns=None if pair is None else pair[0], last_pose_ns=last_pose_stamp,
                    namespace=ns, frames={k:config[k] for k in ('world_frame','base_frame','lidar_frame')},
                    processing=timings,batch_sizes={k:len(v) for k,v in batch.items()},
                    cloud=details, tf_source='Gazebo geometry truth, visualization only',
                    imu_units='m/s^2 and rad/s; orientation unavailable')
                status.publish(String(data=json.dumps(health)))
                atomic(directory/'health.json', json.dumps(health).encode())
    finally:
        for _, topic, _ in subscriptions:
            transport.unsubscribe(topic)
        clear(pair[0] if pair else 0)
        atomic(directory/'health.json', json.dumps(dict(source='gazebo-live', online=False,
               error='sensor worker stopped', received_ns=time.monotonic_ns())).encode())
        ros.destroy_node()
        rclpy.shutdown()


def robot_description(c):
    """Explicit schematic visuals. TF origins are the audited actual SDF ones."""
    base, lidar = c['base_frame'], c['lidar_frame']
    def visual(xyz, shape):
        return f'<visual><origin xyz="{xyz}"/><geometry>{shape}</geometry><material name="blue"><color rgba="0.15 0.5 0.8 1"/></material></visual>'
    body = visual('0 0 0','<box size="0.72 0.42 0.16"/>') if c['kind']=='rover' else visual('0 0 0','<box size="0.5 0.05 0.04"/>')+visual('0 0 0','<box size="0.05 0.5 0.04"/>')
    if c.get('vehicle_model')=='wildthumper':
        from .wildthumper_description import schematic
        body=schematic()
    xyz, rpy = ' '.join(map(str,c['mount'][:3])), ' '.join(map(str,c['mount'][3:]))
    return (f'<robot name="mid360_simulation_schematic"><link name="{base}">{body}</link>'
            f'<link name="{lidar}">'+visual('0 0 0','<cylinder radius="0.0325" length="0.06"/>')+'</link>'
            f'<joint name="mid360_mount" type="fixed"><parent link="{base}"/><child link="{lidar}"/>'
            f'<origin xyz="{xyz}" rpy="{rpy}"/></joint></robot>')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        run(json.loads(args.config.read_text()), args.output)
    except Exception as exc:
        atomic(args.output/'health.json', json.dumps(dict(source='gazebo-live', online=False,
            received_ns=time.monotonic_ns(), error=type(exc).__name__+': '+str(exc))).encode())
        raise


if __name__ == '__main__':
    main()
