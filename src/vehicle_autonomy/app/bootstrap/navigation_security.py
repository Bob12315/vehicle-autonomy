"""Fixed native Nav2 cohort ROS permissions; viewers have no Goal/velocity right.

Deployment is a trusted same-host owned simulation. This is not protection
against a process able to read another role's private keystore credentials.
"""
import re


def profiles(namespace):
    if not isinstance(namespace,str) or not re.fullmatch('/nav2_[a-z0-9_]{1,40}',namespace):raise ValueError('one explicit native cohort namespace required')
    ns=namespace;metadata=['get_parameters','get_parameter_types','list_parameters','describe_parameters','set_parameters','set_parameters_atomically','get_type_description']
    common=['/clock','/tf','/tf_static'];scan=['/scan','/odom','/map','/map_updates']
    result={}
    def add(role,node,pub=(),sub=(),execute=(),call=(),reply=(),request=()):
        result[role]=dict(topics=dict(publish=list(pub),subscribe=list(sub)),services=dict(reply=[node+'/'+x for x in metadata]+list(reply),request=list(request)),actions=dict(execute=list(execute),call=list(call)))
    add('bridge','/ros_gz_bridge',pub=['/clock','/phase5/camera/image_raw','/phase5/camera/info','/phase5/scan_raw','/phase5/points','/phase5/imu'])
    add('sensors','/vaf_world_streams',pub=['/odom','/tf','/tf_static','/scan'],reply=['/tf2_frames'],sub=common+['/phase5/camera/image_raw','/phase5/camera/info','/phase5/scan_raw','/phase5/points','/phase5/imu'])
    add('slam','/slam_toolbox',pub=['/map','/map_metadata','/pose','/tf','/slam_toolbox/*'],sub=common+['/scan','/initialpose','/slam_toolbox/*'],reply=['/slam_toolbox/*'])
    native=('planner_server','controller_server','behavior_server','velocity_smoother','collision_monitor','bt_navigator')
    lifecycle=[ns+'/'+node+'/'+service for node in native for service in ('get_state','change_state','get_available_states','get_available_transitions')]
    lifecycle+=['/slam_toolbox/'+service for service in ('get_state','change_state','get_available_states','get_available_transitions')]
    def base(role,node,pub=(),sub=(),execute=(),call=(),reply=(),request=()):
        add(role,ns+'/'+node,pub=list(pub)+[ns+'/'+node+'/transition_event',ns+'/bond'],sub=common+scan+list(sub)+[ns+'/bond'],execute=[ns+'/'+x for x in execute],call=[ns+'/'+x for x in call],reply=[ns+'/'+node+'/*',ns+'/tf2_frames']+list(reply),request=request)
    base('planner','planner_server',pub=[ns+'/plan',ns+'/global_costmap/*'],sub=[ns+'/global_costmap/*'],execute=['compute_path_to_pose','compute_path_through_poses'],reply=[ns+'/global_costmap/*',ns+'/is_path_valid'])
    base('controller','controller_server',pub=[ns+'/cmd_vel_nav',ns+'/marker',ns+'/cost_cloud',ns+'/global_plan',ns+'/local_plan',ns+'/transformed_global_plan',ns+'/received_global_plan',ns+'/evaluation',ns+'/local_costmap/*'],sub=[ns+'/local_costmap/*',ns+'/speed_limit'],execute=['follow_path'],reply=[ns+'/local_costmap/*'])
    base('behaviors','behavior_server',pub=[ns+'/cmd_vel_nav'],sub=[ns+'/local_costmap/costmap_raw',ns+'/local_costmap/costmap_raw_updates',ns+'/local_costmap/published_footprint',ns+'/global_costmap/costmap_raw',ns+'/global_costmap/costmap_raw_updates',ns+'/global_costmap/published_footprint'],execute=['spin','backup','wait'])
    base('smoother','velocity_smoother',pub=[ns+'/cmd_vel_smoothed'],sub=[ns+'/cmd_vel_nav'])
    base('collision','collision_monitor',pub=[ns+'/cmd_vel_final',ns+'/collision_state',ns+'/collision_polygon',ns+'/collision_monitor/collision_points_marker'],sub=[ns+'/cmd_vel_smoothed'])
    base('navigator','bt_navigator',pub=[ns+'/behavior_tree_log'],sub=[ns+'/goal_pose',ns+'/controller_selector',ns+'/planner_selector'],execute=['navigate_to_pose'],call=['navigate_to_pose','compute_path_to_pose','compute_path_through_poses','follow_path','spin','backup','wait'],reply=[ns+'/bt_navigator_navigate_to_pose_rclcpp_node/*'],request=[ns+'/is_path_valid',ns+'/local_costmap/clear_entirely_local_costmap',ns+'/global_costmap/clear_entirely_global_costmap'])
    add('manager','/vaf_native_manager',sub=common+scan+['/pose',ns+'/cmd_vel_nav',ns+'/cmd_vel_smoothed',ns+'/cmd_vel_final',ns+'/plan'],call=[ns+'/'+x for x in ('navigate_to_pose','wait','compute_path_to_pose','follow_path')],request=lifecycle+['/slam_toolbox/serialize_map'])
    add('world_reader','/vaf_slam_streams',sub=common+['/map','/pose'],reply=['/tf2_frames'])
    add('viewer','/vaf_readonly_viewer',sub=common+scan+['/pose','/phase5/camera/image_raw','/phase5/points',ns+'/plan',ns+'/local_plan'],reply=['/vaf_readonly_viewer/reset_time'])
    return result
