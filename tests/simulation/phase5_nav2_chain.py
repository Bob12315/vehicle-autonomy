"""Real native planner/controller/smoother/collision wire qualification.

No motion bridge is assembled. Native velocity must not move the Rover.
"""
import argparse
import json
import os
from pathlib import Path
import time

from tests.simulation.launch import ROOT,install_signal_cleanup
from tests.simulation.phase5_sensors import SensorFixture
from tests.simulation.phase5_slam import start_slam

NODES=(('nav2_planner','planner_server'),('nav2_controller','controller_server'),('nav2_behaviors','behavior_server'),('nav2_velocity_smoother','velocity_smoother'),('nav2_collision_monitor','collision_monitor'),('nav2_bt_navigator','bt_navigator'))


def _is_control(row):
    from pymavlink.dialects.v20 import ardupilotmega as mav
    parser=mav.MAVLink(None)
    return any(m.get_type()!='TIMESYNC' for m in parser.parse_buffer(bytes.fromhex(row['raw_hex'])) or [])


def run(path,*,secure=False):
    f=SensorFixture(path,source_time_sync=True,secure=secure);report={'passed':False,'motion_bridge_assembled':False,'motion_requested':False}
    os.environ['VAF_SLAM_BOUNDARY_LIBRARY']=str((ROOT/'artifacts/phase5-world-navigation/slam-boundary/libvaf_slam_boundary.so').resolve())
    try:
        f.start();start_slam(f,'slam',ROOT/'simulation/phase5/slam_mapping.yaml');origin=f.truth()
        graph=f.ros_start('graph-readiness',[str(ROOT/'scripts/with_ros2.sh'),'/usr/bin/python3','-m','tests.simulation.nav2_graph_probe','--result',str(path/'graph-readiness.json')],role='manager',transient=True)
        try:graph.wait(timeout=15)
        finally:f.owned.stop_process(graph)
        # Use the native ROS interpreter for YAML; it is not a base dependency.
        original=ROOT/'simulation/phase5/nav2_rover.yaml';namespace='/nav2_wire';config=path/'nav2.yaml'
        # YAML indentation wraps all exact node/costmap names in the namespace.
        config.write_text('nav2_wire:\n'+''.join('  '+line if line.strip() else line for line in original.read_text().splitlines(keepends=True)))
        wrapper=str(ROOT/'scripts/with_ros2.sh')
        for package,node in NODES:
            command=[wrapper,'/usr/bin/python3','-m','vehicle_autonomy.app.bootstrap.ros2_run',package,node,'--ros-args','--params-file',str(config),'-r','__ns:='+namespace]
            if node in ('controller_server','behavior_server'):command+=['-r','cmd_vel:=cmd_vel_nav']
            if node=='velocity_smoother':command+=['-r','cmd_vel:=cmd_vel_nav','-r','cmd_vel_smoothed:=cmd_vel_smoothed']
            f.ros_start(node,command,role={'planner_server':'planner','controller_server':'controller','behavior_server':'behaviors','velocity_smoother':'smoother','collision_monitor':'collision','bt_navigator':'navigator'}[node])
        for _,node in NODES:
            for transition in ('configure','activate'):
                name=node+'-'+transition
                p=f.ros_start(name,[wrapper,'/usr/bin/python3','-m','vehicle_autonomy.app.bootstrap.ros2_lifecycle','--node',namespace+'/'+node,'--transition',transition,'--result',str(path/(name+'.json'))],role='manager',transient=True)
                try:code=p.wait(timeout=25)
                finally:f.owned.stop_process(p)
                if code:raise RuntimeError(name+' failed')
        if secure:
            viewer=f.ros_start('readonly-viewer-injection',[wrapper,'/usr/bin/python3','-m','tests.simulation.nav2_viewer_probe','--namespace',namespace,'--result',str(path/'viewer-denial.json')],role='viewer',transient=True)
            try:code=viewer.wait(timeout=15)
            finally:f.owned.stop_process(viewer)
            if code:raise RuntimeError('actual read-only viewer isolation failed')
        p=f.ros_start('native-wire-probe',[wrapper,'/usr/bin/python3','-m','tests.simulation.nav2_chain_probe','--namespace',namespace,'--world',f.owned.world,'--result',str(path/'wire.json')],role='manager',transient=True)
        try:code=p.wait(timeout=60)
        finally:f.owned.stop_process(p)
        if code:raise RuntimeError('actual native wire probe failed')
        report['actual']=json.loads((path/'wire.json').read_text());truth=f.truth()
        displacement=((truth.x_m-origin.x_m)**2+(truth.y_m-origin.y_m)**2)**.5
        assert displacement<.05 and not any(_is_control(x) for x in f.writer),'native ROS velocities escaped without an Action bridge'
        report.update(passed=True,truth_displacement_m=displacement,writer_calls=len(f.writer),control_writer_calls=0)
    except BaseException as exc:report['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        try:f.close()
        finally:(path/'summary.json').write_text(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--secure',action='store_true');a=p.parse_args();install_signal_cleanup();print(run(a.run_dir.resolve(),secure=a.secure)['passed'],flush=True)
