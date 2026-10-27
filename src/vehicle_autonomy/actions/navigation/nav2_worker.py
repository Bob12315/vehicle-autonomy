"""One managed native ROS Goal macro and authenticated final-chain data reader.

No vehicle transport/Execution exists here. Original controller stamps are
mapped using the owned Gazebo public producer clock, independently of the
Smoother/Collision Monitor's receive times. All output remains data-only.
"""
import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import time
from uuid import UUID,uuid4
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.engine.navigation.mailbox import NavigationBinding,NavigationCommand
from vehicle_autonomy.engine.navigation.source_evidence import ControllerEvidence,ControllerStamp
from vehicle_autonomy.world.mapping.grid import atomic_json
from vehicle_autonomy.world.sensors.simulation_time import SimulationGenerationClock


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path,required=True);args,ros_args=parser.parse_known_args()
    c=json.loads(args.config.read_text())
    if set(c)!={'schema','directory','namespace','world','clock_domain','goal','source_receiver'} or c['schema']!=1:raise ValueError('strict native Goal profile required')
    goal=c['goal'];fields={'goal_id','action_id','target_id','vehicle_session','world_generation','map_epoch','x_m','y_m','yaw_rad','provider_id','provider_epoch'}
    if type(goal) is not dict or set(goal)!=fields:raise ValueError('sealed native Goal binding required')
    UUID(hex=goal['goal_id'])
    for name in ('x_m','y_m','yaw_rad'):
        if type(goal[name]) not in (float,int) or not math.isfinite(goal[name]) or abs(goal[name])>(math.pi if name=='yaw_rad' else 5):raise ValueError('qualified native Goal coordinate bounds')
    root=Path(c['directory']);namespace=c['namespace'];generation=SimulationGenerationClock(c['world'])
    def host():return TimePoint(time.monotonic_ns(),datetime.now(timezone.utc),c['clock_domain'])
    from vehicle_autonomy.world.navigation.source_ipc import NativeSourceSocket
    descriptor=c['source_receiver'];inlet=NativeSourceSocket(descriptor['address'],descriptor['pid'],descriptor['start_ticks'])
    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.action import ActionClient
    from nav2_msgs.action import NavigateToPose,Wait,FollowPath
    from geometry_msgs.msg import TwistStamped,PoseWithCovarianceStamped,PoseStamped
    from action_msgs.msg import GoalStatus
    from unique_identifier_msgs.msg import UUID as RosUUID
    from builtin_interfaces.msg import Duration
    rclpy.init(args=ros_args);node=Node('vaf_managed_native_goal',start_parameter_services=False,parameter_overrides=[Parameter('use_sim_time',value=True)])
    latest_pose=[]
    pose_subscription=node.create_subscription(PoseWithCovarianceStamped,'/pose',lambda m:latest_pose.__setitem__(slice(None),[m]),1)
    evidence=ControllerEvidence(host());phase='PREPARING';binding=None;raw_gids={};command=None;sequence=0;last_source=-1;dropped=0;last_write=0;fault=None;rejections=[]
    def stamp(m):return m.header.stamp.sec*1_000_000_000+m.header.stamp.nanosec
    def twist(m):
        v=m.twist;values=(v.linear.x,v.linear.y,v.linear.z,v.angular.x,v.angular.y,v.angular.z)
        if any(not math.isfinite(v) for v in values) or any(abs(values[i])>1e-9 for i in (1,2,3,4)):raise ValueError('native Rover requires finite full planar Twist')
        if m.header.frame_id!='base_link':raise ValueError('native controller frame changed')
        return values
    def received_at(info):
        actual=host();value=info['host_received_ns']
        return TimePoint(value,actual.utc-__import__('datetime').timedelta(microseconds=(actual.monotonic_ns-value)//1000),actual.clock_domain_id)
    def raw(m,info):
        nonlocal dropped
        if not raw_gids:return
        try:
            expected=raw_gids['behavior_server' if phase in ('PREPARING','PREPARE_CANCEL') else 'controller_server']
            if bytes(info['publisher_gid']).hex()!=expected:raise ValueError('raw source does not belong to current macro phase')
            received=received_at(info);captured=generation.lower_bound(stamp(m),host())
            evidence.record(ControllerStamp(stamp(m),captured,received,twist(m)),host())
        except (ValueError,LookupError) as exc:
            dropped+=1
            if len(rejections)<16:rejections.append(dict(topic='raw',error=str(exc),gid=bytes(info['publisher_gid']).hex(),source_ns=stamp(m)))
    def final(m,info):
        nonlocal command,sequence,last_source,dropped
        if binding is None or phase not in ('PREPARE_CANCEL','CONTROLLER_PREPARE','ACTIVE'):return
        try:
            if bytes(info['publisher_gid']).hex()!=binding.producer_gid:raise ValueError('final producer changed')
            values=twist(m);received=received_at(info);original=evidence.original(stamp(m),host())
            if abs(values[0])>.3 or abs(values[5])>.35:raise ValueError('native configured velocity limit')
            if phase!='ACTIVE' and (values[0]!=0 or values[5]!=0):raise ValueError('preparation must provide an actual native zero')
            if stamp(m)<=last_source:return
            sequence+=1;last_source=stamp(m)
            command=to_json_value(NavigationCommand(binding,sequence,stamp(m),original.captured_at,received,values[0],values[5]))
        except (ValueError,LookupError) as exc:
            dropped+=1
            if len(rejections)<16:rejections.append(dict(topic='final',error=str(exc),gid=bytes(info['publisher_gid']).hex(),source_ns=stamp(m)))
    def receive_sources():
        for frame in inlet.drain():
            message=TwistStamped();message.header.stamp.sec,message.header.stamp.nanosec=divmod(frame.source_ns,1_000_000_000);message.header.frame_id=frame.frame_id
            message.twist.linear.x,message.twist.linear.y,message.twist.linear.z,message.twist.angular.x,message.twist.angular.y,message.twist.angular.z=frame.values
            info=dict(publisher_gid=frame.gid,host_received_ns=frame.received_ns)
            (raw if frame.channel==0 else final)(message,info)
    def state():
        nonlocal last_write
        now=time.monotonic_ns()
        if now-last_write<20_000_000:return
        last_write=now;atomic_json(root/'state.json',dict(goal_id=goal['goal_id'],state='RUNNING',published_ns=now,feedback=dict(phase=phase,command=command,dropped_source=dropped)))
    def spin_until(predicate,timeout,label,*,abort_on_cancel=True):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            rclpy.spin_once(node,timeout_sec=.01);receive_sources();state()
            if abort_on_cancel and (root/'cancel.json').exists():raise InterruptedError('managed Goal cancelled')
            if predicate():return
        raise TimeoutError(label)
    def publishers():
        raw=node.get_publishers_info_by_topic(namespace+'/cmd_vel_nav');final=node.get_publishers_info_by_topic(namespace+'/cmd_vel_final')
        return raw,final
    def topology_ready():
        raw,final=publishers()
        return len(raw)==2 and {p.node_name for p in raw}=={'controller_server','behavior_server'} and len(final)==1 and final[0].node_name=='collision_monitor' and all(p.node_namespace==namespace for p in raw+final)
    result={'goal_id':goal['goal_id'],'state':'UNKNOWN'}
    try:
        spin_until(lambda:bool(generation.samples) and topology_ready(),10,'qualified native publisher topology')
        raw_info,final_info=publishers();raw_gids={p.node_name:bytes(p.endpoint_gid).hex() for p in raw_info}
        binding=NavigationBinding(goal['action_id'],goal['target_id'],goal['provider_id'],goal['provider_epoch'],goal['vehicle_session'],goal['world_generation'],goal['goal_id'],bytes(final_info[0].endpoint_gid).hex(),c['clock_domain'])
        wait_client=ActionClient(node,Wait,namespace+'/wait')
        if not wait_client.wait_for_server(timeout_sec=10):raise TimeoutError('native Wait server unavailable')
        # Initial encrypted delivery can complete discovery only after the
        # first write. Each retry below is a NEW harmless native Wait, permitted
        # only after the preceding native cancellation result is CANCELED.
        # An old zero is never retimed or admitted past its 200 ms source age.
        for preparation_attempt in range(3):
            phase='PREPARING';preparation=Wait.Goal();preparation.time=Duration(sec=10)
            request=wait_client.send_goal_async(preparation);spin_until(request.done,5,'native preparation acceptance');handle=request.result()
            if not handle.accepted:raise RuntimeError('native preparation explicitly rejected')
            outcome=handle.get_result_async();started=time.monotonic()
            settling=1.5 if preparation_attempt==0 else .1
            spin_until(lambda:time.monotonic()-started>=settling,3,'encrypted data chain preparation')
            phase='PREPARE_CANCEL';cancel=handle.cancel_goal_async();spin_until(cancel.done,5,'native preparation cancellation')
            if not cancel.result().goals_canceling:raise RuntimeError('native preparation cancel not confirmed')
            spin_until(outcome.done,5,'native preparation terminal')
            if outcome.result().status!=GoalStatus.STATUS_CANCELED:raise RuntimeError('native preparation did not end cancelled')
            try:
                spin_until(lambda:command is not None and host().monotonic_ns-command['captured_at']['monotonic_ns']<200_000_000,.5,'fresh actual native zero through final chain')
                break
            except TimeoutError:
                if preparation_attempt==2:raise
        result['preparation_goals']=preparation_attempt+1
        # Establish the actual CONTROLLER publisher's encrypted channel too.
        # Each harmless current-pose FollowPath must end SUCCEEDED before a
        # new preparation or the one real Navigate Goal may be submitted.
        # No preparatory output is ever allowed onto the vehicle stream.
        controller=ActionClient(node,FollowPath,namespace+'/follow_path')
        if not controller.wait_for_server(timeout_sec=10):raise TimeoutError('native controller unavailable')
        for controller_attempt in range(3):
            phase='CONTROLLER_PREPARE';before=sequence
            spin_until(lambda:bool(latest_pose),5,'fresh native pose for stationary preparation')
            pose=latest_pose[-1];capture=generation.lower_bound(stamp(pose),host(),strict_previous=True)
            if host().elapsed_ns_since(capture)>500_000_000 or pose.header.frame_id!='map':raise ValueError('native preparation pose expired/frame mismatch')
            preparation=FollowPath.Goal();preparation.path.header.frame_id='map';preparation.path.header.stamp=node.get_clock().now().to_msg()
            point=PoseStamped();point.header=preparation.path.header;point.pose=pose.pose.pose
            preparation.path.poses=[point,point];preparation.controller_id='FollowPath';preparation.goal_checker_id='goal_checker'
            request=controller.send_goal_async(preparation);spin_until(request.done,5,'controller preparation acceptance');handle=request.result()
            if not handle.accepted:raise RuntimeError('controller preparation rejected')
            outcome=handle.get_result_async();spin_until(outcome.done,5,'controller preparation terminal')
            if outcome.result().status!=GoalStatus.STATUS_SUCCEEDED:raise RuntimeError('controller stationary preparation not proven successful')
            try:
                spin_until(lambda:command is not None and sequence>before and host().monotonic_ns-command['captured_at']['monotonic_ns']<200_000_000,.5,'fresh controller zero through final chain')
                break
            except TimeoutError:
                if controller_attempt==2:raise
        result['controller_preparation_goals']=controller_attempt+1
        client=ActionClient(node,NavigateToPose,namespace+'/navigate_to_pose')
        if not client.wait_for_server(timeout_sec=10):raise TimeoutError('native NavigateToPose server unavailable')
        request_goal=NavigateToPose.Goal();request_goal.pose.header.frame_id='map';request_goal.pose.header.stamp=node.get_clock().now().to_msg()
        request_goal.pose.pose.position.x=float(goal['x_m']);request_goal.pose.pose.position.y=float(goal['y_m']);request_goal.pose.pose.orientation.z=math.sin(goal['yaw_rad']/2);request_goal.pose.pose.orientation.w=math.cos(goal['yaw_rad']/2)
        # Native BT plugins, with no autonomous Spin/BackUp recovery outside
        # the controller source admitted by this macro.
        from vehicle_autonomy._resources import resource_root
        request_goal.behavior_tree=str(resource_root()/'simulation/phase5/navigate_rover.xml')
        request=client.send_goal_async(request_goal,goal_uuid=RosUUID(uuid=list(UUID(hex=goal['goal_id']).bytes)));spin_until(request.done,5,'native navigation acceptance');handle=request.result()
        if not handle.accepted:raise RuntimeError('native navigation explicitly rejected')
        if bytes(handle.goal_id.uuid)!=UUID(hex=goal['goal_id']).bytes:raise ValueError('native Goal UUID changed')
        outcome=handle.get_result_async();phase='ACTIVE';cancelled=False;deadline=time.monotonic()+65
        while not outcome.done():
            rclpy.spin_once(node,timeout_sec=.01);receive_sources();state()
            if not topology_ready():raise RuntimeError('native publisher topology changed')
            if (root/'cancel.json').exists() and not cancelled:handle.cancel_goal_async();cancelled=True
            if time.monotonic()>deadline:raise TimeoutError('native Goal macro deadline')
        status=outcome.result().status
        result.update(state={GoalStatus.STATUS_SUCCEEDED:'SUCCEEDED',GoalStatus.STATUS_CANCELED:'CANCELLED',GoalStatus.STATUS_ABORTED:'FAILED'}.get(status,'UNKNOWN'),native_status=status)
    except InterruptedError:result.update(state='CANCELLED',error='cancelled during native preparation')
    except Exception as exc:result.update(state='UNKNOWN',error=type(exc).__name__+': '+str(exc)[:160])
    finally:
        result['source_rejections']=rejections
        result['clock_diagnostic']=dict(samples=len(generation.samples),fault=generation.fault,delayed=generation.delayed)
        raw_info,final_info=publishers();result['publisher_diagnostic']={k:[dict(name=p.node_name,ns=p.node_namespace,gid=bytes(p.endpoint_gid).hex()) for p in rows] for k,rows in (('raw',raw_info),('final',final_info))}
        # The terminal file is the one logical-result handoff. Only the
        # registered parent publishes EXITING with that result; a separate
        # result-less child EXITING status would race the two file reads.
        atomic_json(root/'terminal.json',result);generation.close();inlet.close();node.destroy_node();rclpy.shutdown()


if __name__=='__main__':main()
