"""Private Nav2 Planner Server owner. No controller, BT navigator or vehicle I/O."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from mapping.grid import MapStore, atomic_json
from planning.models import PlanningError, Pose2D


def run(directory):
    import rclpy
    from rclpy.action import ActionClient
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from geometry_msgs.msg import PoseStamped, TransformStamped
    from lifecycle_msgs.srv import ChangeState
    from lifecycle_msgs.msg import Transition
    from nav_msgs.msg import OccupancyGrid
    from nav2_msgs.action import ComputePathToPose
    from nav2_msgs.srv import GetCostmap
    from tf2_ros import StaticTransformBroadcaster
    from ament_index_python.packages import get_package_prefix

    data = json.loads((directory/"request.json").read_text())
    grid = MapStore(directory/"maps").load(data["grid_sha256"])
    namespace = "/vaf_plan_"+data["request_id"]
    frame = "grid_"+data["request_id"]
    anchor = "planning_anchor_"+data["request_id"]
    ros_args = ["--ros-args","-r",f"__ns:={namespace}","-r","/tf:=tf","-r","/tf_static:=tf_static"]
    parameters = {
        namespace+"/planner_server":{"ros__parameters":{
            "use_sim_time":False,"bond_heartbeat_period":0.,"expected_planner_frequency":0.,
            "planner_plugins":["GridBased"],"costmap_update_timeout":2.,
            "GridBased.plugin":"nav2_smac_planner::SmacPlanner2D",
            "GridBased.tolerance":0.,"GridBased.allow_unknown":False,
            "GridBased.downsample_costmap":False,"GridBased.max_planning_time":2.,
            "GridBased.smoother.max_iterations":0}},
        namespace+"/global_costmap/global_costmap":{"ros__parameters":{
            "use_sim_time":False,"global_frame":frame,"robot_base_frame":anchor,
            "robot_radius":0.,"footprint_padding":0.,"update_frequency":10.,"publish_frequency":1.,
            "rolling_window":False,"track_unknown_space":True,"transform_tolerance":.2,
            "resolution":float(grid.resolution_m),"plugins":["static_layer"],
            "static_layer.plugin":"nav2_costmap_2d::StaticLayer",
            "static_layer.map_subscribe_transient_local":True,"static_layer.subscribe_to_updates":False,
            "static_layer.map_topic":namespace+"/map","always_send_full_costmap":True}}}
    atomic_json(directory/"planner.yaml", parameters)
    rclpy.init(args=ros_args)
    node = Node("request_owner")
    planner = None
    summary = {"ok":False,"request_id":data["request_id"],"map_sha256":data["map_sha256"],"frame_epoch":data["frame_epoch"]}
    log = (directory/"planner.log").open("wb")

    def check_time():
        if time.monotonic_ns() >= data["deadline_ns"]:
            raise PlanningError("TIMEOUT","Nav2 request deadline exceeded")
        if planner is not None and planner.poll() is not None:
            raise PlanningError("BACKEND_FAILURE",f"Nav2 planner exited {planner.returncode}")

    def await_future(future):
        while not future.done():
            check_time()
            rclpy.spin_once(node,timeout_sec=.02)
        if future.exception() is not None:raise future.exception()
        return future.result()

    def call(client, request):
        while not client.wait_for_service(timeout_sec=.05):
            check_time()
            rclpy.spin_once(node,timeout_sec=.01)
        return await_future(client.call_async(request))

    try:
        qos = QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL)
        publisher = node.create_publisher(OccupancyGrid,"map",qos)
        message = OccupancyGrid()
        message.header.frame_id = frame
        message.header.stamp = node.get_clock().now().to_msg()  # Snapshot publication, not sensor capture.
        message.info.resolution = float(grid.resolution_m)
        message.info.width, message.info.height = grid.width,grid.height
        message.info.origin.orientation.w = 1.
        message.data = list(grid.cells)
        publisher.publish(message)
        broadcaster = StaticTransformBroadcaster(node)
        transform = TransformStamped()
        transform.header.frame_id,transform.child_frame_id = frame,anchor
        transform.transform.rotation.w = 1.
        broadcaster.sendTransform(transform)
        # This anchor only satisfies costmap lifecycle TF; use_start=True always.
        executable = Path(get_package_prefix("nav2_planner"))/"lib/nav2_planner/planner_server"
        planner = subprocess.Popen([str(executable),*ros_args,"--params-file",str(directory/"planner.yaml")],stdout=log,stderr=subprocess.STDOUT)
        atomic_json(directory/"native-process.json",{"pid":planner.pid,"pgid":os.getpgid(planner.pid)})
        client = node.create_client(ChangeState,"planner_server/change_state")
        for transition in (Transition.TRANSITION_CONFIGURE,Transition.TRANSITION_ACTIVATE):
            request = ChangeState.Request();request.transition.id = transition
            if not call(client,request).success:
                raise PlanningError("BACKEND_FAILURE","Nav2 lifecycle transition rejected")
        costmap_client = node.create_client(GetCostmap,"global_costmap/get_costmap")
        observed = call(costmap_client,GetCostmap.Request()).map
        expected = [254 if v else 0 for v in grid.cells]
        origin = observed.metadata.origin
        if observed.header.frame_id != frame or not math.isclose(observed.metadata.resolution,grid.resolution_m,rel_tol=1e-6) or observed.metadata.size_x != grid.width or observed.metadata.size_y != grid.height or list(observed.data) != expected or any(abs(v)>1e-8 for v in (origin.position.x,origin.position.y,origin.position.z,origin.orientation.x,origin.orientation.y,origin.orientation.z,origin.orientation.w-1)):
            raise PlanningError("BACKEND_FAILURE","Nav2 costmap differs from the pinned configuration grid")
        summary["costmap_verified"] = True
        summary["nav2_version"] = ET.parse(Path(get_package_prefix("nav2_planner"))/"share/nav2_planner/package.xml").findtext("version")

        def pose(values):
            p = Pose2D(*values)
            result = PoseStamped();result.header.frame_id = frame
            result.header.stamp = node.get_clock().now().to_msg()
            result.pose.position.x,result.pose.position.y = float(p.x),float(p.y)
            result.pose.orientation.z,result.pose.orientation.w = math.sin(p.yaw/2),math.cos(p.yaw/2)
            return result

        action = ActionClient(node,ComputePathToPose,"compute_path_to_pose")
        while not action.wait_for_server(timeout_sec=.05):
            check_time();rclpy.spin_once(node,timeout_sec=.01)
        goal = ComputePathToPose.Goal()
        goal.start,goal.goal,goal.use_start,goal.planner_id = pose(data["start"]),pose(data["goal"]),True,"GridBased"
        handle = await_future(action.send_goal_async(goal))
        if not handle.accepted:raise PlanningError("NO_PATH","Nav2 rejected the planning goal")
        response = await_future(handle.get_result_async())
        result = response.result
        if response.status != 4 or result.error_code != 0:
            raise PlanningError("NO_PATH",f"Nav2 planning failed: status={response.status}, error_code={result.error_code}, {getattr(result,'error_msg','')}")
        if result.path.header.frame_id != frame or not 1 <= len(result.path.poses) <= 8192:
            raise PlanningError("INVALID_PATH","Nav2 path frame/size mismatch")
        points = []
        for p in result.path.poses:
            if p.header.frame_id != frame or abs(p.pose.position.z) > 1e-6:
                raise PlanningError("INVALID_PATH","Nav2 returned nonplanar or mixed-frame poses")
            q = p.pose.orientation
            if abs(q.x)>1e-6 or abs(q.y)>1e-6 or abs(q.z*q.z+q.w*q.w-1)>1e-6:
                raise PlanningError("INVALID_PATH","Nav2 returned an invalid planar orientation")
            points.append([p.pose.position.x,p.pose.position.y,math.atan2(2*q.w*q.z,1-2*q.z*q.z)])
        # Only this private namespace is inspected; foreign DDS participants do
        # not grant authority or become map/TF sources for this request.
        topics = [name for name,types in node.get_topic_names_and_types() if name.startswith(namespace+"/")]
        if any("cmd_vel" in name or "setpoint" in name for name in topics):
            raise PlanningError("BACKEND_FAILURE","unexpected motion-command topic in private planner graph")
        summary.update(ok=True,poses=points,topics=topics,planner="nav2_smac_planner::SmacPlanner2D")
    except Exception as exc:
        summary.update(code=getattr(exc,"code","BACKEND_FAILURE"),error=f"{type(exc).__name__}: {exc}")
    finally:
        if planner is not None:
            planner.terminate()
            try:planner.wait(timeout=3)
            except subprocess.TimeoutExpired:planner.kill();planner.wait(timeout=2)
            summary["planner_returncode"] = planner.returncode
        log.close()
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
        atomic_json(directory/"response.json",summary)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1])))
