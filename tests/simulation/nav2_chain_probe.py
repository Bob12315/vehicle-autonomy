"""Native Nav2 wire probe; no vehicle port, writer or Gazebo actuator."""
import argparse
from collections import deque
import json
from pathlib import Path
import time


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--namespace',required=True);p.add_argument('--world',required=True);p.add_argument('--result',type=Path,required=True);a,ros_args=p.parse_known_args()
    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.action import ActionClient
    from nav2_msgs.action import NavigateToPose,Wait,ComputePathToPose
    from geometry_msgs.msg import TwistStamped
    from builtin_interfaces.msg import Duration
    from action_msgs.msg import GoalStatus,GoalStatusArray
    from rclpy.qos import qos_profile_action_status_default
    from datetime import datetime,timezone
    from vehicle_autonomy.contracts.core.time import TimePoint
    from vehicle_autonomy.world.sensors.simulation_time import SimulationGenerationClock
    from vehicle_autonomy.engine.navigation.source_evidence import ControllerEvidence,ControllerStamp
    def host():return TimePoint(time.monotonic_ns(),datetime.now(timezone.utc),'host-monotonic')
    generation=SimulationGenerationClock(a.world);evidence=ControllerEvidence(host());qualified=[];rejected=[]
    rclpy.init(args=ros_args);node=Node('vaf_nav2_wire_probe',parameter_overrides=[Parameter('use_sim_time',value=True)],start_parameter_services=False)
    values={k:deque(maxlen=256) for k in ('cmd_vel_nav','cmd_vel_smoothed','cmd_vel_final')};report={'passed':False,'vehicle_writer_calls':0};prefix=a.namespace.rstrip('/')
    def stamp(m):return m.header.stamp.sec*1_000_000_000+m.header.stamp.nanosec
    def receive(topic,m):
        received=host();source=stamp(m);values[topic].append(dict(stamp=source,frame=m.header.frame_id,v=float(m.twist.linear.x),w=float(m.twist.angular.z),received=received.monotonic_ns))
        try:
            if topic=='cmd_vel_nav':
                captured=generation.lower_bound(source,received);v=m.twist
                evidence.record(ControllerStamp(source,captured,received,(v.linear.x,v.linear.y,v.linear.z,v.angular.x,v.angular.y,v.angular.z)),received)
            if topic=='cmd_vel_final':
                original=evidence.original(source,received)
                qualified.append(dict(stamp=source,age_ns=received.monotonic_ns-original.captured_at.monotonic_ns,v=m.twist.linear.x,w=m.twist.angular.z))
        except (ValueError,LookupError) as exc:
            if len(rejected)<256:rejected.append(dict(topic=topic,error=str(exc)))
    navigation_goals=set()
    def observe_goal_status(message):
        for status in message.status_list:navigation_goals.add(bytes(status.goal_info.goal_id.uuid).hex())
    node.create_subscription(GoalStatusArray,prefix+'/navigate_to_pose/_action/status',observe_goal_status,qos_profile_action_status_default)
    for topic in values:node.create_subscription(TwistStamped,prefix+'/'+topic,lambda m,t=topic:receive(t,m),10)
    def spin_until(predicate,timeout,label):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            rclpy.spin_once(node,timeout_sec=.02)
            if predicate():return
        raise TimeoutError(label)
    def send(kind,name,goal):
        client=ActionClient(node,kind,prefix+'/'+name)
        if not client.wait_for_server(timeout_sec=15):raise RuntimeError(name+' native server unavailable')
        future=client.send_goal_async(goal);spin_until(future.done,5,name+' acceptance');handle=future.result()
        if not handle.accepted:raise RuntimeError(name+' native goal rejected')
        return client,handle,handle.get_result_async()
    try:
        spin_until(lambda:bool(generation.samples),5,'public Gazebo producer clock')
        start_clock=time.monotonic();spin_until(lambda:time.monotonic()-start_clock>.1,1,'admitted generation clock history')
        wait=Wait.Goal();wait.time=Duration(sec=10)
        client,handle,result=send(Wait,'wait',wait)
        # Wait remains a real active native subgoal while encrypted endpoints
        # match. Never refresh the eventual zero's original source timestamp.
        settling=time.monotonic();spin_until(lambda:time.monotonic()-settling>=1.5,3,'encrypted native chain preparation')
        cancellation=handle.cancel_goal_async();spin_until(cancellation.done,5,'stationary native Wait cancellation response');assert cancellation.result().goals_canceling
        spin_until(result.done,5,'stationary native Wait cancellation result')
        assert result.result().status==GoalStatus.STATUS_CANCELED
        spin_until(lambda:len(values['cmd_vel_final'])>=1,3,'actual warmup zero through complete chain')
        report['warmup']={k:list(v) for k,v in values.items()}
        assert any(v['v']==0 and v['w']==0 for v in qualified),'warmup zero lacks fresh original producer evidence'
        assert all(x['v']==0 and x['w']==0 for x in values['cmd_vel_final'])
        planner=ComputePathToPose.Goal();planner.goal.header.frame_id='map';planner.goal.header.stamp=node.get_clock().now().to_msg();planner.goal.pose.position.x=1.5;planner.goal.pose.orientation.w=1.;planner.planner_id='GridBased'
        client,handle,result=send(ComputePathToPose,'compute_path_to_pose',planner);spin_until(result.done,10,'actual native path')
        assert result.result().status==GoalStatus.STATUS_SUCCEEDED
        report['path_points']=len(result.result().result.path.poses);assert report['path_points']>=5
        goal=NavigateToPose.Goal();goal.pose=planner.goal
        client,handle,result=send(NavigateToPose,'navigate_to_pose',goal)
        spin_until(lambda:any(abs(v['v'])>0 or abs(v['w'])>0 for v in values['cmd_vel_final']),10,'actual final native velocity')
        start=time.monotonic();spin_until(lambda:time.monotonic()-start>=1.,3,'native velocity sampling')
        assert sum(abs(v['v'])>0 or abs(v['w'])>0 for v in values['cmd_vel_final'])>=10,'normal final control stream is not continuously available'
        cancel=handle.cancel_goal_async();spin_until(cancel.done,5,'native goal cancellation response');assert cancel.result().goals_canceling
        spin_until(result.done,6,'native canceled terminal');report['native_cancel_status']=result.result().status
        assert report['native_cancel_status']==GoalStatus.STATUS_CANCELED
        report['accepted_navigation_goals']=sorted(navigation_goals)
        assert navigation_goals=={bytes(handle.goal_id.uuid).hex()},'foreign or missing native navigation Goal'
        report['wire']={k:list(v) for k,v in values.items()};report['publishers']={k:[dict(name=p.node_name,namespace=p.node_namespace,gid=bytes(p.endpoint_gid).hex()) for p in node.get_publishers_info_by_topic(prefix+'/'+k)] for k in values}
        final=values['cmd_vel_final'];assert final and all(abs(v['v'])<=.3 and abs(v['w'])<=.35 for v in final)
        assert len(report['publishers']['cmd_vel_final'])==1 and report['publishers']['cmd_vel_final'][0]['name']=='collision_monitor'
        raw_stamps={v['stamp'] for v in values['cmd_vel_nav']};report['native_unmatched_final_stamps']=[v['stamp'] for v in final if v['stamp'] not in raw_stamps]
        # Native timeout decay/cancel may stamp without a fresh raw input.
        # Such frames must be refused by independent ControllerEvidence.
        assert all(v['stamp'] in raw_stamps for v in qualified)
        report['qualified_final']=qualified;report['rejected_source']=rejected;report['generation_clock_samples']=len(generation.samples)
        assert sum(abs(x['v'])+abs(x['w'])>0 for x in qualified)>=10,'original producer-time control evidence unavailable'
        report['passed']=True
    except BaseException as exc:report['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        report['qualified_final']=qualified;report['rejected_source']=rejected;report['generation_clock_samples']=len(generation.samples)
        report['observed_wire']={k:list(v) for k,v in values.items()}
        report['observed_publishers']={k:[dict(name=p.node_name,namespace=p.node_namespace,gid=bytes(p.endpoint_gid).hex(),type=p.topic_type) for p in node.get_publishers_info_by_topic(prefix+'/'+k)] for k in values}
        a.result.write_text(json.dumps(report,indent=2));generation.close();node.destroy_node();rclpy.shutdown()


if __name__=='__main__':main()
