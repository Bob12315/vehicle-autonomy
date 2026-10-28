"""Explicit optional ROS worker. No ROS import occurs in the framework server.

The Nav2 service uses an isolated /vaf_tools namespace and publishes no MAVLink
commands. Its ROS endpoints are discovery metadata, not navigation authority.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


NODES = (('nav2_planner', 'planner_server'), ('nav2_controller', 'controller_server'),
         ('nav2_behaviors', 'behavior_server'), ('nav2_velocity_smoother', 'velocity_smoother'),
         ('nav2_collision_monitor', 'collision_monitor'), ('nav2_bt_navigator', 'bt_navigator'))


def namespace():
    return os.environ.get('ROS_NAMESPACE', '/').rstrip('/') or ''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('observe', 'graph', 'rviz', 'nav2', 'start-nav2'))
    parser.add_argument('--params', type=Path); parser.add_argument('--behavior-tree', type=Path)
    a = parser.parse_args()
    import rclpy
    from rclpy.node import Node
    from rclpy.action import get_action_names_and_types
    from lifecycle_msgs.srv import GetState, ChangeState
    rclpy.init(args=[])
    ns = namespace(); node = Node('vaf_tool_observer' if a.operation == 'observe' else 'vaf_tool_probe', namespace=ns or '/')
    stop = False
    def stopping(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, stopping); signal.signal(signal.SIGTERM, stopping)
    children = []
    def call(client, request, timeout=2):
        end = time.monotonic() + timeout
        while not stop and time.monotonic() < end:
            if client.wait_for_service(timeout_sec=.1): break
        else: raise TimeoutError('ROS service unavailable')
        future = client.call_async(request)
        while not stop and not future.done() and time.monotonic() < end: rclpy.spin_once(node, timeout_sec=.05)
        if not future.done() or future.result() is None: raise TimeoutError('ROS service response unavailable')
        return future.result()
    try:
        if a.operation == 'start-nav2':
            if a.params is None or a.behavior_tree is None: raise ValueError('trusted Nav2 params and behavior tree required')
            from ament_index_python.packages import get_package_prefix
            native_ns = ns + '/vaf_tools'
            with tempfile.TemporaryDirectory(prefix='nav2-', dir=Path.cwd()) as temporary:
                config = Path(temporary) / 'nav2.yaml'
                content = a.params.read_text().replace('use_sim_time: true', 'use_sim_time: false').replace('behavior_plugins: [spin, backup, wait]', 'behavior_plugins: [wait]')
                config.write_text(native_ns.lstrip('/') + ':\n' + ''.join('  ' + line if line.strip() else line for line in content.splitlines(keepends=True)))
                for package, executable in NODES:
                    binary = Path(get_package_prefix(package))/'lib'/package/executable
                    command = [str(binary), '--ros-args', '--params-file', str(config), '-r', '__ns:=' + native_ns]
                    if executable == 'bt_navigator': command += ['-p', 'default_nav_to_pose_bt_xml:=' + str(a.behavior_tree)]
                    if executable in ('controller_server', 'behavior_server'): command += ['-r', 'cmd_vel:=cmd_vel_tool_candidate']
                    if executable == 'velocity_smoother': command += ['-r', 'cmd_vel:=cmd_vel_tool_candidate', '-r', 'cmd_vel_smoothed:=cmd_vel_tool_smoothed']
                    if executable == 'collision_monitor': command += ['-p', 'cmd_vel_in_topic:=cmd_vel_tool_smoothed', '-p', 'cmd_vel_out_topic:=cmd_vel_tool_isolated']
                    children.append(subprocess.Popen(command, stdin=subprocess.DEVNULL))
                for _, executable in NODES:
                    for transition in (1, 3):
                        client = node.create_client(ChangeState, native_ns + '/' + executable + '/change_state')
                        request = ChangeState.Request(); request.transition.id = transition
                        if not call(client, request, 25).success: raise RuntimeError('Nav2 lifecycle rejected: ' + executable)
                        node.destroy_client(client)
                print('Native Nav2 lifecycle active; cmd_vel isolated; no vehicle writer', flush=True)
                while not stop:
                    if any(c.poll() is not None for c in children): raise RuntimeError('Nav2 child exited')
                    rclpy.spin_once(node, timeout_sec=.1)
            return 0
        if a.operation == 'observe':
            while not stop:
                print(json.dumps(dict(nodes=node.get_node_names_and_namespaces(), topics=node.get_topic_names_and_types(),
                    services=node.get_service_names_and_types(), actions=get_action_names_and_types(node))), flush=True)
                for _ in range(10):
                    if stop: break
                    rclpy.spin_once(node, timeout_sec=.1)
            return 0
        until = time.monotonic() + .8
        while not stop and time.monotonic() < until: rclpy.spin_once(node, timeout_sec=.05)
        nodes = {nspace.rstrip('/') + '/' + name for name, nspace in node.get_node_names_and_namespaces()}
        topics = dict(node.get_topic_names_and_types()); actions = dict(get_action_names_and_types(node))
        result = dict(nodes=sorted(nodes), topics=topics, actions=actions, lifecycle={})
        if a.operation == 'graph': ready = ns + '/vaf_tool_observer' in nodes
        elif a.operation == 'rviz':
            from tf2_msgs.msg import TFMessage
            received = []
            sub = node.create_subscription(TFMessage, ns + '/tf', lambda msg:received.append(bool(msg.transforms)), 10)
            until = time.monotonic() + .7
            while not stop and time.monotonic() < until: rclpy.spin_once(node, timeout_sec=.05)
            ready = ns + '/vaf_rviz' in nodes and any(received)
            node.destroy_subscription(sub)
        else:
            native_ns = ns + '/vaf_tools'
            for _, executable in NODES:
                client = node.create_client(GetState, native_ns + '/' + executable + '/get_state')
                result['lifecycle'][executable] = call(client, GetState.Request(), .3).current_state.id
                node.destroy_client(client)
            ready = all(v == 3 for v in result['lifecycle'].values()) and 'nav2_msgs/action/NavigateToPose' in actions.get(native_ns + '/navigate_to_pose', [])
        result['status'] = 'READY' if ready else 'WAITING'
        print(json.dumps(result), flush=True)
        return 0 if ready else 2
    finally:
        for child in children:
            if child.poll() is None: child.terminate()
        for child in children:
            try: child.wait(timeout=2)
            except subprocess.TimeoutExpired: child.kill(); child.wait()
        node.destroy_node(); rclpy.shutdown()


if __name__ == '__main__': raise SystemExit(main())
