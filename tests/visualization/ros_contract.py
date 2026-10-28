"""Real ROS/DDS worker contracts with EXPLICIT synthetic VehicleState fixtures.

Not an RViz GUI, real sensor or SITL acceptance. No vehicle writer is present.
"""
import argparse,json,os,signal,subprocess,sys,time
from pathlib import Path
from tests.web_ui.helpers import Harness
from .helpers import gps
from vehicle_autonomy.app.web.server import load_token


def run(directory):
    directory.mkdir(mode=0o700,parents=True,exist_ok=False);h=Harness(directory/'backend',kinds=('rover','copter'));gps(h)
    credential=directory/'visualization.private';h.server.visualization_token=load_token(credential)
    config=directory/'source.json';config.write_text(json.dumps(dict(schema=1,url=h.base,token_file=str(credential.resolve()),use_sim_time=True)))
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile,ReliabilityPolicy
    from nav_msgs.msg import Odometry,Path as RosPath
    from rosgraph_msgs.msg import Clock
    from std_msgs.msg import String
    from tf2_msgs.msg import TFMessage
    rclpy.init(args=[]);node=Node('vaf_clock_contract_fixture');clock=node.create_publisher(Clock,'/clock',10)
    status={};counts={'rover':0,'copter':0};empty={'rover':False,'copter':False};processes=[];logs=[];summary=dict(passed=False,source=__doc__)
    base=20_000_000_000;started=time.monotonic_ns();paused=False;frozen=None
    def status_update(m,key):status[key]=json.loads(m.data)
    def odom(m,key):
        counts[key]+=1
        assert m.header.frame_id=='contract_'+key+'/viz/odom' and m.child_frame_id=='contract_'+key+'/viz/base_link'
    def path(m,key):empty[key]|=not m.poses
    qos=QoSProfile(depth=20,reliability=ReliabilityPolicy.BEST_EFFORT)
    for kind in counts:
        topic='/contract_'+kind+'/viz'
        node.create_subscription(String,topic+'/status',lambda m,k=kind:status_update(m,k),qos)
        node.create_subscription(Odometry,topic+'/odometry',lambda m,k=kind:odom(m,k),qos)
        node.create_subscription(RosPath,topic+'/trajectory',lambda m,k=kind:path(m,k),qos)
        cwd=directory/kind;cwd.mkdir();log=(cwd/'worker.log').open('w');logs.append(log)
        env=dict(os.environ,VAF_VEHICLE_ID=kind,VAF_VEHICLE_TYPE=kind,VAF_ENVIRONMENT='simulation',ROS_NAMESPACE='/contract_'+kind,VAF_VISUALIZATION_KIND=kind)
        processes.append(subprocess.Popen([sys.executable,'-m','vehicle_autonomy.app.visualization.worker','--config',str(config.resolve())],env=env,cwd=cwd,stdout=log,stderr=subprocess.STDOUT))
    def tick():
        nonlocal frozen
        value=frozen if paused else base+(time.monotonic_ns()-started)
        message=Clock();message.clock.sec,message.clock.nanosec=divmod(value,1_000_000_000);clock.publish(message)
        rclpy.spin_once(node,timeout_sec=.02)
        assert all(p.poll() is None for p in processes),'ROS worker exited'
    def wait(predicate,seconds=12):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            tick()
            if predicate():return
        raise AssertionError('ROS contract timeout: '+json.dumps(status))
    def valid(kind):return status.get(kind,{}).get('valid') is True
    try:
        wait(lambda:all(valid(k) and counts[k]>3 for k in counts));summary['real_standard_odometry_and_namespaces']=True
        assert node.count_publishers('/contract_rover/viz/tf')==1 and node.count_publishers('/contract_copter/viz/tf')==1
        h.drivers['rover'].fresh=False;wait(lambda:not valid('rover') and valid('copter'));before=counts['rover']
        end=time.monotonic()+.5
        while time.monotonic()<end:tick()
        assert counts['rover']==before and empty['rover'];summary['stale_pose_not_republished']=True
        h.drivers['rover'].fresh=True;wait(lambda:valid('rover'))
        conflict=node.create_publisher(TFMessage,'/contract_rover/viz/tf',10)
        wait(lambda:not valid('rover') and 'conflicting' in status['rover']['reason']);node.destroy_publisher(conflict);wait(lambda:valid('rover'));summary['tf_conflict_fails_closed_and_recovers']=True
        frozen=base+(time.monotonic_ns()-started);paused=True
        wait(lambda:all(not valid(k) and 'clock' in status[k]['reason'] for k in counts));summary['clock_pause_clears_live_data']=True
        paused=False;wait(lambda:all(valid(k) for k in counts))
        previous={k:int(status[k]['stamp_ns']) for k in counts}
        for k in empty:empty[k]=False
        base-=10_000_000_000;wait(lambda:all(valid(k) and int(status[k]['stamp_ns'])<previous[k] for k in counts));summary['clock_rewind_readmitted_without_old_path']=all(empty.values())
        old=h.server.visualization_token;h.server.visualization_token='revoked-'+old
        wait(lambda:all(not valid(k) for k in counts));h.server.visualization_token=old;wait(lambda:all(valid(k) for k in counts));summary['feed_auth_revocation_and_recovery']=True
        assert not h.lab.runtime.views() and not any(d.writes for d in h.drivers.values())
        summary.update(passed=True,counts=counts,zero_vehicle_writes=True,final_status=status)
    finally:
        for p in processes:
            if p.poll() is None:p.terminate()
        for p in processes:p.wait(5)
        for log in logs:log.close()
        node.destroy_node();rclpy.shutdown();h.close();credential.unlink(missing_ok=True)
        (directory/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args()
    print(json.dumps(run(a.run_dir.resolve()),ensure_ascii=False))
