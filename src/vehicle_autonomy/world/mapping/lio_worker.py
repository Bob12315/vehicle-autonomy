"""Owned ROS sidecar for estimated LIO data; no truth or vehicle port inputs.

FAST-LIO owns its private algorithm TF topic. This sidecar alone owns the
display TF island and exports capture-stamped read-only Localization inputs.
"""
import argparse
from collections import OrderedDict, deque
from array import array
import json,math
from pathlib import Path
import signal
import time
from multiprocessing import get_context
from queue import Empty,Full

from vehicle_autonomy.world.mapping.clock import RosClockBridge
from vehicle_autonomy.world.mapping.lio_timing import scan_coverage,capture_trace
from vehicle_autonomy.world.sensors.camera.live import atomic


def run(config, directory):
    import numpy as np
    from vehicle_autonomy.contracts.core.geometry import Quaternion,Vector3
    from vehicle_autonomy.world.transform.tree import rotate_vector,multiply_quaternions
    import rclpy
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, qos_profile_sensor_data
    from builtin_interfaces.msg import Time
    from geometry_msgs.msg import TransformStamped, PoseStamped
    from nav_msgs.msg import Odometry, Path as RosPath
    from sensor_msgs.msg import PointCloud2, PointField, Imu
    from sensor_msgs_py import point_cloud2
    from rosgraph_msgs.msg import Clock
    from tf2_msgs.msg import TFMessage
    from std_msgs.msg import String
    from livox_ros_driver2.msg import CustomMsg
    from vehicle_autonomy.world.sensors.lidar.mid360_worker import robot_description

    if config['sensor']['backend']!='livox-gz-sliced-pattern-v1':
        raise ValueError('LIO requires timed simulation input')
    sensor=config['sensor'];ns=sensor['namespace'];prefix=ns+'/slam'
    frames=config['frames'];generation=config['generation']
    rclpy.init(args=[])
    node=Node('vaf_lio_adapter',namespace=prefix,parameter_overrides=[Parameter('use_sim_time',value=True)])
    reliable=QoSProfile(depth=20,reliability=ReliabilityPolicy.RELIABLE)
    retained=QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL)
    pubs={key:node.create_publisher(kind,prefix+'/'+key,qos) for key,kind,qos in (
        ('registered',PointCloud2,qos_profile_sensor_data),('admitted_pose',PoseStamped,reliable),('map',PointCloud2,retained),
        ('raw',PointCloud2,qos_profile_sensor_data),('trajectory',RosPath,reliable),
        ('tf',TFMessage,reliable),('tf_static',TFMessage,retained),('robot_description',String,retained),
        ('pgo_map_display',PointCloud2,retained),('pgo_path_display',RosPath,reliable),('relocated_trajectory',RosPath,reliable),
        ('relocated_registered',PointCloud2,qos_profile_sensor_data))}
    clock=RosClockBridge();pending={'odom':OrderedDict(),'cloud':OrderedDict(),'timing':OrderedDict()}
    from vehicle_autonomy.world.sensors.simulation_time import SimulationGenerationClock
    from vehicle_autonomy.world.localization.lio_input import at
    generation_clock=SimulationGenerationClock(sensor['world']) if config['source']=='live' else None
    context=get_context('spawn');map_queue=context.Queue(maxsize=2);map_results=context.Queue(maxsize=2)
    map_stop=context.Event();map_state={};map_dropped=0;map_heartbeat=time.monotonic_ns()
    state=dict(schema=1,generation=generation,frame_id=frames['map'],revision=0,online=False,
        error='awaiting paired FAST-LIO output',localization=None,counts={},dropped=0,
        quality='DEGRADED',covariance=None,twist_source='finite difference of LIO poses in simulation time',
        pose_semantics='local inertial odometry; no global alignment or relocalization claim')
    fault=None;pins={};last_clock_host=0;last_source=-1;last_pose=None;last_graph=0.
    last_imu=None;scan_captures=OrderedDict();capture_traces=OrderedDict();capture_sequences=OrderedDict();first_source=None;first_input_sequence=None;tracking_inputs=0
    trajectory=deque(maxlen=2000);last_path_sample=-1;last_path_publish=0.;last_state=0.;last_static=0.;stopped=False
    admitted_stamps=deque(maxlen=200);relocated_path=deque(maxlen=1000);relocation_source=None;relocation_epoch=None;relocation_revision=0;last_relocation_poll=0.
    admitted_clouds=OrderedDict()

    def stamp(value):
        out=Time();out.sec,out.nanosec=divmod(value,1_000_000_000);return out
    def ns_stamp(value):return value.sec*1_000_000_000+value.nanosec
    def transform(parent,child,position,quaternion,when):
        msg=TransformStamped();msg.header.frame_id=parent;msg.child_frame_id=child;msg.header.stamp=stamp(when)
        msg.transform.translation.x,msg.transform.translation.y,msg.transform.translation.z=map(float,position)
        msg.transform.rotation.x,msg.transform.rotation.y,msg.transform.rotation.z,msg.transform.rotation.w=map(float,quaternion)
        return msg
    def on_clock(message):
        nonlocal fault,last_clock_host
        now=time.monotonic_ns();value=ns_stamp(message.clock)
        if clock.observe(value,now):fault='simulation clock epoch changed; explicit restart required'
        if clock.pairs:last_clock_host=clock.pairs[-1][1]
    def receive(key):
        def cb(message):
            nonlocal fault
            value=ns_stamp(message.header.stamp)
            if value<=last_source:
                state['dropped']+=1;return
            if value in pending[key]:fault='duplicate algorithm source stamp';return
            pending[key][value]=(message,time.monotonic_ns())
            while len(pending[key])>20:pending[key].popitem(last=False);state['dropped']+=1
        return cb
    def input_timing(message):
        nonlocal fault,last_imu
        try:
            if len(message.data)>8192:raise ValueError('algorithm input timing budget')
            value=json.loads(message.data);stamps=value['imu_capture_times_ns']
            if not isinstance(stamps,list) or not 1<=len(stamps)<=100 or any(type(t) is not int or t<0 for t in stamps):raise ValueError('invalid actual IMU input stamps')
            for key in ('source_begin_ns','source_end_ns'):
                if type(value[key]) is not int or value[key]<0:raise ValueError('invalid source scan timing')
            pending['timing'][value['source_end_ns']]=(value,time.monotonic_ns());last_imu=time.monotonic_ns()
            while len(pending['timing'])>20:pending['timing'].popitem(last=False)
        except (ValueError,KeyError,TypeError) as exc:fault=str(exc)
    def custom(message):
        state['counts']['input_scans']=state['counts'].get('input_scans',0)+1
        if message.points:
            from collections import Counter
            counts=Counter(message.timebase+p.offset_time for p in message.points);captures=sorted(counts)
            scan_captures[message.timebase]=(captures,state['counts']['input_scans'],counts)
            while len(scan_captures)>40:scan_captures.popitem(last=False)
    def acquisition_trace(message):
        nonlocal fault
        try:
            if len(message.data)>4096:raise ValueError('capture trace budget')
            value=capture_trace(json.loads(message.data));base=value['timebase_ns']
            state['counts']['source_scan_events']=state['counts'].get('source_scan_events',0)+1
            capture_traces[base]=value;capture_sequences[base]=state['counts']['source_scan_events']
            while len(capture_traces)>40:capture_traces.popitem(last=False);capture_sequences.popitem(last=False)
        except (ValueError,KeyError,TypeError) as exc:fault=str(exc)
    def raw(message):
        # The bridge already preserves every original CustomMsg point offset
        # in its packed PointCloud2. Audit that packed array directly instead
        # of deserializing thousands of Python CustomPoint objects a second
        # time. Renderer events independently check the counts/timestamps.
        # Old recordings without capture evidence keep the CustomMsg observer.
        nonlocal fault
        if not message.width:
            # The visualization bridge explicitly clears a stale display with
            # an empty marker. It is not a new acquired scan or a malformed
            # point. Let genuine pose/clock freshness withdraw localization.
            state['counts']['empty_display_markers']=state['counts'].get('empty_display_markers',0)+1
            message.header.frame_id=frames['lidar'];pubs['raw'].publish(message);return
        if sensor.get('capture_topic'):
            try:
                from vehicle_autonomy.world.sensors.lidar.mid360_timed_data import packed_capture_times
                begin,times,counts=packed_capture_times(message,sensor['lidar_frame'])
                state['counts']['input_scans']=state['counts'].get('input_scans',0)+1
                scan_captures[begin]=(times,state['counts']['input_scans'],counts)
                while len(scan_captures)>40:scan_captures.popitem(last=False)
                state['source_timing_audit']='packed original CustomMsg point offsets + independent renderer capture events'
            except ValueError as exc:fault=str(exc);return
        message.header.frame_id=frames['lidar'];pubs['raw'].publish(message)
    node.create_subscription(Clock,'/clock',on_clock,reliable)
    node.create_subscription(Odometry,prefix+'/odometry_raw',receive('odom'),reliable)
    node.create_subscription(PointCloud2,prefix+'/registered_raw',receive('cloud'),reliable)
    # Audit FAST-LIO's actual receiver, rather than treating loss in a second
    # Python IMU observer as loss in the estimator. Original stamps only.
    node.create_subscription(String,prefix+'/input_timing',input_timing,reliable)
    if not sensor.get('capture_topic'):node.create_subscription(CustomMsg,ns+'/custom',custom,reliable)
    if sensor.get('capture_topic'):node.create_subscription(String,sensor['capture_topic'],acquisition_trace,reliable)
    node.create_subscription(PointCloud2,ns+'/points',raw,qos_profile_sensor_data)
    pgo_pins={};pgo_epoch=None;pgo_authority_checked={};last_pgo_path=0.
    def pgo_authority(topic):
        now=time.monotonic()
        if topic in pgo_pins and now-pgo_authority_checked.get(topic,0.)<.25:return
        entries=node.get_publishers_info_by_topic(topic)
        if len(entries)!=1 or entries[0].node_name!='vaf_sc_pgo':raise ValueError('unqualified PGO publisher')
        gid=bytes(entries[0].endpoint_gid).hex()
        if topic in pgo_pins and pgo_pins[topic]!=gid:raise ValueError('PGO publisher changed; restart required')
        pgo_pins[topic]=gid
        pgo_authority_checked[topic]=now
    def pgo_status(message):
        try:
            pgo_authority(prefix+'/pgo/status')
            if len(message.data)>2048:raise ValueError('PGO status budget')
            value=json.loads(message.data)
            for key in ('optimizer_revision','applied_loop_constraints','keyframes','capture_ros_ns'):
                if type(value[key]) is not int or value[key]<0:raise ValueError('invalid PGO status')
            state['pgo']=dict(value,received_host_ns=time.monotonic_ns(),error=None,
                semantics='historical optimized keyframes; never an adopted control position')
        except (ValueError,KeyError,TypeError) as exc:state['pgo']=dict(error=str(exc))
    def pgo_map(message):
        try:
            pgo_authority(prefix+'/pgo/map')
            if message.header.frame_id!='map' or not 0<message.width<=500000 or ns_stamp(message.header.stamp)<=0:raise ValueError('PGO map frame/capture provenance unavailable')
            # Both algorithms retain the first LIO gauge. This is an audited
            # coordinate-name alias, no latest-TF conversion or truth alignment.
            message.header.frame_id=frames['map'];pubs['pgo_map_display'].publish(message)
        except ValueError as exc:state['pgo_map_error']=str(exc)
    def pgo_path(message):
        nonlocal last_pgo_path
        try:
            pgo_authority(prefix+'/pgo/trajectory')
            if message.header.frame_id!='map' or len(message.poses)>1000:raise ValueError('PGO path frame/resource budget')
            # The upstream historical Path is serialized at 10 Hz. It has no
            # role in LIO input admission; bound display work to 2 Hz so a
            # growing optional graph cannot starve the live pose/timing cuts.
            if time.monotonic()-last_pgo_path<.5:return
            message.header.frame_id=frames['map']
            for pose in message.poses:pose.header.frame_id=frames['map']
            pubs['pgo_path_display'].publish(message)
            last_pgo_path=time.monotonic()
        except ValueError as exc:state['pgo_path_error']=str(exc)
    node.create_subscription(String,prefix+'/pgo/status',pgo_status,reliable)
    node.create_subscription(PointCloud2,prefix+'/pgo/map',pgo_map,reliable)
    node.create_subscription(RosPath,prefix+'/pgo/trajectory',pgo_path,QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE))

    def graph():
        nonlocal fault
        sensor_node='vaf_mid360' if config['source']=='live' else 'rosbag2_player'
        expected={prefix+'/odometry_raw':'vaf_fast_lio',prefix+'/registered_raw':'vaf_fast_lio',
            prefix+'/input_timing':'vaf_fast_lio',
            ns+'/imu':sensor_node,ns+'/custom':sensor_node,'/clock':sensor_node,
            prefix+'/tf':'vaf_lio_adapter',prefix+'/tf_static':'vaf_lio_adapter'}
        if sensor.get('capture_topic'):expected[sensor['capture_topic']]=sensor_node
        for topic,name in expected.items():
            entries=node.get_publishers_info_by_topic(topic)
            if len(entries)!=1 or entries[0].node_name!=name:
                if topic in pins:fault='publisher authority changed: '+topic
                raise LookupError('awaiting unique '+name+' for '+topic)
            gid=bytes(entries[0].endpoint_gid).hex()
            if topic in pins and pins[topic]!=gid:fault='publisher restarted: '+topic
            pins[topic]=gid

    def consume(source,odometry,cloud,timing,received,now):
        nonlocal last_source,last_pose,first_source,first_input_sequence,tracking_inputs,last_path_sample,last_path_publish
        began=time.monotonic_ns()
        if odometry.header.frame_id!='camera_init' or odometry.child_frame_id!='body' or cloud.header.frame_id!='camera_init':
            raise ValueError('unexpected FAST-LIO input coordinate frames')
        if generation_clock:
            try:capture=generation_clock.lower_bound(source,at(now),strict_previous=True).monotonic_ns
            except ValueError as exc:
                if generation_clock.fault:raise
                raise LookupError(str(exc)) from exc
        else:
            # Replay receipt clock supplies only a causal lower bound. Never
            # interpolate a late clock receipt forward past original data.
            candidates=[host for sim,host in clock.pairs if 0<=source-sim<=100_000_000 and host<=received]
            if not candidates:raise LookupError('awaiting causal replay clock correlation')
            capture=max(candidates)
        if capture>received:raise ValueError('LIO capture precedes its clock correlation')
        if not 0<=now-capture<=1_000_000_000:raise TimeoutError('LIO capture expired')
        if not last_imu or now-last_imu>1_000_000_000:raise ValueError('IMU source expired')
        original_begin=next((t for t in scan_captures if abs(t-timing['source_begin_ns'])<=2),None)
        if original_begin is None:raise LookupError('awaiting original CustomMsg capture times for algorithm output')
        returns,input_sequence,return_counts=scan_captures[original_begin]
        if sensor.get('capture_topic'):
            if original_begin not in capture_traces:raise LookupError('awaiting actual renderer capture trace')
            trace=capture_traces[original_begin];captures=trace['capture_times_ns']
            # The independent reliable renderer event sequence is the input
            # denominator. Loss in the best-effort display observer cannot
            # silently shrink the measured dropped-scan fraction.
            input_sequence=capture_sequences[original_begin]
            if not set(returns)<=set(captures) or any(return_counts.get(t,0)!=n for t,n in zip(captures,trace['return_counts'])):
                raise ValueError('actual return points disagree with renderer capture trace')
        else:captures=returns
        # A slice can have no valid returns, or preprocessing can remove its
        # returns. Bind the original packet by its header, never by an assumed
        # last-return stamp. Reject this scan rather than inventing point times.
        if len(captures)!=5 or not captures[0]-2<=source<=captures[-1]+2:
            state['scan_quality_rejections']=state.get('scan_quality_rejections',0)+1
            state['last_rejected_scan']=dict(timing=timing,capture_times_ns=captures,
                reason='insufficient return slices or estimator end outside original capture interval')
            raise TimeoutError('scan not admitted: original capture coverage incomplete')
        retained=timing.get('point_capture_times_ns',[])
        used=[]
        for value in retained:
            original=next((t for t in returns if abs(t-value)<=2),None)
            if original is None:raise ValueError('retained point time is not an actual return capture')
            used.append(original)
        try:coverage=scan_coverage(timing['imu_capture_times_ns'],captures,return_times=sorted(set(used)),pose_time_ns=source)
        except (ValueError,TimeoutError) as exc:
            if first_source is not None:raise
            state['initialization_unqualified_pairs']=state.get('initialization_unqualified_pairs',0)+1
            raise TimeoutError('initialization scan lacks qualified IMU coverage: '+str(exc)) from exc
        p=odometry.pose.pose.position;q=odometry.pose.pose.orientation
        xyz=np.array([p.x,p.y,p.z]);quat=np.array([q.x,q.y,q.z,q.w])
        if not np.isfinite(np.r_[xyz,quat]).all() or abs(np.linalg.norm(quat)-1)>1e-6:raise ValueError('invalid estimated pose')
        rotation=Quaternion(*quat)
        # FAST-LIO state is the IMU origin; mount/IMU offsets are measured in
        # the unchanged model assembly, never inferred from Gazebo truth.
        offset=rotate_vector(rotation,Vector3(*(np.array(sensor['mount'][:3])+np.array(sensor['imu_in_lidar'][:3]))))
        xyz=xyz-np.array([offset.x,offset.y,offset.z])
        twist=None
        if last_pose:
            dt=(source-last_pose[0])/1e9
            distance=float(np.linalg.norm(xyz-last_pose[1]));old=last_pose[2]
            delta=multiply_quaternions(rotation,Quaternion(-old.x,-old.y,-old.z,old.w))
            axis=np.array([delta.x,delta.y,delta.z])*(1 if delta.w>=0 else -1)
            norm=float(np.linalg.norm(axis));angle=2*math.atan2(norm,abs(delta.w))
            if dt<=0 or distance>max(.5,5*dt) or angle>max(.4,3*dt):raise ValueError('LIO pose discontinuity')
            twist=dict(linear=((xyz-last_pose[1])/dt).tolist(),angular=(axis*(angle/max(norm,1e-15)/dt)).tolist())
        values=point_cloud2.read_points_numpy(cloud,field_names=('x','y','z','intensity'),skip_nans=False)
        nonlocal map_dropped
        try:map_queue.put_nowait((source,capture,values.copy()))
        except Full:
            try:map_queue.get_nowait()
            except Empty:pass
            map_dropped+=1
            try:map_queue.put_nowait((source,capture,values.copy()))
            except Full:pass  # Bounded IPC feeder may still own the old slot.
        cloud.header.frame_id=frames['odom'];pubs['registered'].publish(cloud)
        # Retain a bounded set of the original admitted messages. A slower
        # map matcher can display only its exact capture, never newer scans
        # with an old alignment or a fabricated current transform stamp.
        admitted_clouds[source]=cloud
        while len(admitted_clouds)>20 or sum(len(v.data) for v in admitted_clouds.values())>32*1024*1024:
            admitted_clouds.popitem(last=False)
        pubs['tf'].publish(TFMessage(transforms=[
            transform(frames['map'],frames['odom'],[0,0,0],[0,0,0,1],source),
            transform(frames['odom'],frames['base'],xyz,quat,source)]))
        pose=PoseStamped();pose.header.frame_id=frames['map'];pose.header.stamp=stamp(source)
        pose.pose.position.x,pose.pose.position.y,pose.pose.position.z=map(float,xyz)
        pose.pose.orientation=q
        pose.header.frame_id=frames['odom'];pubs['admitted_pose'].publish(pose);pose.header.frame_id=frames['map']
        if source-last_path_sample>=200_000_000:
            trajectory.append(pose);last_path_sample=source
        # Re-serializing an ever-growing 10 Hz Path delayed the small IMU/pose
        # stream. Display samples remain capture-stamped; odometry and TF keep
        # their full rate. The display history is bounded and sent at 2 Hz.
        if trajectory and time.monotonic()-last_path_publish>=.5:
            path=RosPath();path.header=trajectory[-1].header;path.poses=list(trajectory)
            pubs['trajectory'].publish(path);last_path_publish=time.monotonic()
        publication=time.monotonic_ns();state['revision']+=1
        if first_source is None:first_source=source;first_input_sequence=input_sequence
        tracking_inputs=input_sequence-first_input_sequence+1
        state['scan_delivery']=dict(tracking_input_scans=tracking_inputs,paired_outputs=state['revision'],
            dropped_fraction=max(0.,1.-state['revision']/tracking_inputs) if tracking_inputs else None,
            scope='actual CustomMsg capture ends within admitted tracking interval; initialization separately counted',
            first_capture_ros_ns=first_source)
        state['localization']=dict(capture_ros_ns=source,captured_host_ns=capture,published_host_ns=publication,
            position=xyz.tolist(),quaternion=quat.tolist(),derived_twist=twist)
        state['counts']['paired']=state['revision'];state['latency_host_ms']=(publication-capture)/1e6
        state['adapter_processing_ms']=(publication-began)/1e6
        state['trajectory_display']=dict(points=len(trajectory),sample_interval_sim_s=.2,max_publish_host_hz=2,max_points=2000)
        state['scan_coverage']=coverage
        state['input_timing_source']='original stamps at FAST-LIO actual IMU receiver; no estimator math changes'
        state['imu_max_gap_sim_ns']=max(state.get('imu_max_gap_sim_ns',0),coverage['imu_bracket_max_gap_ns'])
        state['scan_imu_nearest_ns']=coverage['point_imu_max_skew_ns']
        last_source=source;last_pose=(source,xyz,rotation)
        admitted_stamps.append(source)

    def publish_relocation():
        nonlocal relocation_source,relocation_epoch,relocation_revision
        marker=directory/'relocation-source.json'
        if not marker.exists():return
        try:
            from vehicle_autonomy.world.localization.lio_input import LioWorldSource
            import re
            binding=json.loads(marker.read_text());epoch=binding['generation']
            if not isinstance(epoch,str) or not re.fullmatch('[0-9a-f]{32}',epoch):raise ValueError('invalid relocation epoch')
            if epoch!=relocation_epoch:
                relocation_source=LioWorldSource(directory/'relocation'/epoch,epoch,binding['frame_id'],max_age_ns=750_000_000,
                    producer='fast-lio-localization2');relocation_epoch=epoch;relocation_revision=0;relocated_path.clear()
            result=relocation_source.update(owner_running=state['online'])
            if result.localization is None:raise LookupError(relocation_source.error)
            raw_state=relocation_source.raw;revision=raw_state['revision']
            alignment=raw_state['map_to_local_odom'];when=alignment['capture_ros_ns']
            if when!=raw_state['localization']['capture_ros_ns'] or when not in admitted_stamps:raise LookupError('waiting for admitted LIO cut at map-match time')
            if when not in admitted_clouds:raise LookupError('matched scan no longer in bounded capture history')
            q=Quaternion(*alignment['quaternion']);p=Vector3(*alignment['position'])
            if revision>relocation_revision:
                pubs['tf'].publish(TFMessage(transforms=[transform(binding['frame_id'],frames['map'],
                    [p.x,p.y,p.z],[q.x,q.y,q.z,q.w],when)]))
                pubs['relocated_registered'].publish(admitted_clouds[when])
                pose=PoseStamped();pose.header.frame_id=binding['frame_id'];pose.header.stamp=stamp(when)
                actual=result.localization.pose.value
                pose.pose.position.x,pose.pose.position.y,pose.pose.position.z=actual.position.x,actual.position.y,actual.position.z
                pose.pose.orientation.x,pose.pose.orientation.y,pose.pose.orientation.z,pose.pose.orientation.w=actual.orientation.x,actual.orientation.y,actual.orientation.z,actual.orientation.w
                relocated_path.append(pose);path=RosPath();path.header=pose.header;path.poses=list(relocated_path)
                pubs['relocated_trajectory'].publish(path);relocation_revision=revision
            state['relocation_tf']=dict(online=True,map_id=binding['map_id'],frame_id=binding['frame_id'],
                capture_ros_ns=when,generation=epoch,authority='vaf_lio_adapter',error=None)
        except (OSError,ValueError,TypeError,KeyError,LookupError) as exc:
            state['relocation_tf']=dict(online=False,error=str(exc))

    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    from vehicle_autonomy.world.mapping.cloud_map_worker import accumulate
    mapping=context.Process(target=accumulate,args=(config,directory,map_queue,map_results,map_stop),name='bounded-lio-map')
    mapping.start()
    try:
        while not stopped and rclpy.ok():
            rclpy.spin_once(node,timeout_sec=.005);now=time.monotonic_ns();error=fault
            marker=directory/'pgo-epoch'
            current_pgo_epoch=marker.read_text() if marker.exists() else None
            if current_pgo_epoch!=pgo_epoch:pgo_pins.clear();pgo_authority_checked.clear();state.pop('pgo',None);pgo_epoch=current_pgo_epoch
            try:
                if now/1e9-last_graph>.25:graph();last_graph=now/1e9
                if fault:raise ValueError(fault)
                if not clock.pairs or now-last_clock_host>750_000_000:raise LookupError('simulation clock unavailable/paused')
                if (directory/'fault-tf').exists():raise ValueError('injected TF output interruption; explicit restart required')
                for source in sorted(pending['odom'].keys() & pending['cloud'].keys() & pending['timing'].keys()):
                    odom,ot=pending['odom'][source];cloud,ct=pending['cloud'][source]
                    timing,tt=pending['timing'][source]
                    try:consume(source,odom,cloud,timing,min(ot,ct,tt),now)
                    except LookupError:continue
                    except TimeoutError as exc:
                        state['dropped']+=1;state['expired_pairs']=state.get('expired_pairs',0)+1
                        state['last_pair_error']=dict(reason=str(exc),source_ros_ns=source,
                            received_host_ns=min(ot,ct,tt),observed_host_ns=now)
                    del pending['odom'][source];del pending['cloud'][source];del pending['timing'][source]
                pose=state.get('localization')
                # Leave budget for the 100 ms exchange and owner monitor so
                # read-only World state is withdrawn within the 1 s bound.
                if not pose or now-pose['captured_host_ns']>750_000_000:
                    if now-last_clock_host>250_000_000:raise LookupError('LIO output expired; simulation clock paused/unavailable')
                    raise LookupError('LIO output expired/uninitialized')
                if not last_imu or now-last_imu>1_000_000_000:raise LookupError('IMU source expired')
            except LookupError as exc:error=str(exc)
            except ValueError as exc:fault=str(exc);error=fault
            state.update(online=error is None,error=error,published_host_ns=now,publishers=pins,fault_latched=fault is not None)
            if now/1e9-last_relocation_poll>=.1:publish_relocation();last_relocation_poll=now/1e9
            if now/1e9-last_static>1:
                when=clock.pairs[-1][0] if clock.pairs else 0
                pubs['tf_static'].publish(TFMessage(transforms=[transform(frames['base'],frames['lidar'],sensor['mount'][:3],[0,0,0,1],when)]))
                model=dict(sensor,base_frame=frames['base'],lidar_frame=frames['lidar'])
                pubs['robot_description'].publish(String(data=robot_description(model)));last_static=now/1e9
            for _ in range(2):
                try:map_state,payload=map_results.get_nowait()
                except Empty:break
                map_heartbeat=map_state['map_worker']['heartbeat_host_ns']
                if payload is not None:
                    source,count,data=payload
                    fields=[PointField(name=name,offset=i*4,datatype=PointField.FLOAT32,count=1) for i,name in enumerate(('x','y','z','intensity'))]
                    message=PointCloud2();message.header.frame_id=frames['map'];message.header.stamp=stamp(source)
                    message.height=1;message.width=count;message.fields=fields;message.point_step=16;message.row_step=count*16
                    message.is_dense=True;message.data=array('B',data);pubs['map'].publish(message)
            state.update(map_state)
            if not mapping.is_alive() or now-map_heartbeat>2_000_000_000:
                state['map']=dict(state.get('map',{}),error='map process stopped/stale; LIO pose remains separate')
            state['map_queue_overwrites']=map_dropped
            if now/1e9-last_state>.1:
                state['clock_observation']=dict(simulation_ns=clock.pairs[-1][0] if clock.pairs else None,
                    last_changed_host_ns=last_clock_host,paused_by_age=now-last_clock_host>750_000_000)
                state['pending_inputs']={key:dict(count=len(values),latest_ros_ns=max(values) if values else None)
                    for key,values in pending.items()}
                atomic(directory/'state.json',json.dumps(state,allow_nan=False).encode());last_state=now/1e9
    finally:
        map_stop.set();map_queue.cancel_join_thread();mapping.join(5)
        map_queue.close();map_results.close()
        state.update(online=False,error=fault or 'LIO adapter stopped',published_host_ns=time.monotonic_ns())
        atomic(directory/'state.json',json.dumps(state,allow_nan=False).encode())
        if generation_clock:generation_clock.close()
        node.destroy_node();rclpy.shutdown()
        if mapping.is_alive():raise RuntimeError('map process shutdown unconfirmed')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run(json.loads(args.config.read_text()),args.output)


if __name__=='__main__':main()
