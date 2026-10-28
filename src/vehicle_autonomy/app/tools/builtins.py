"""Generate trusted, editable host profiles; no guessed successful installation."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

from vehicle_autonomy._resources import resource_root
from .schema import manifest


def profile(command, *, env=None, health=None, ready=None, connection=None, requires=None, timeout=30):
    return dict(argv=command, env=env or {}, health=health, ready=ready,
                connection=connection or dict(kind='none', description='Connection not configured; process alone is not ready'),
                requires=requires or [], startup_timeout_s=timeout, stop_timeout_s=5)


def make(tool_id, name, kind, profiles, *, permissions=(), dependencies=(), integrations=()):
    return manifest(dict(schema=1, id=tool_id, name=name, type=kind, version='profile-v1 / software version unverified',
        supported_os=['ubuntu-22.04', 'ubuntu-24.04'], dependencies=list(dependencies), install_detection=[],
        profiles=profiles, stop_strategy='owned_process_group', integrations=list(integrations),
        agent_requirements=['user-level', 'posix-process-groups'], permissions=list(permissions)))


def registry(*, ros_env=None, qgc=None, qgc_relay=None, sitl_dir=None, plugin=None):
    root = resource_root(); ros_env = ros_env or {}
    python = sys.executable
    ros = lambda op: dict(argv=[python, '-m', 'vehicle_autonomy.app.tools.ros_tools', op], contains=['"status": "READY"'], timeout_s=3)
    dep = lambda kind, value: dict(kind=kind, value=str(value))
    ros_deps = [dep('executable','ros2'), dep('environment','ROS_DISTRO')]
    rviz_config = root/'configs/rviz/navigation-readonly.rviz'
    rviz = make('rviz2', 'RViz2', 'gui', {'default':profile(
        ['rviz2', '-d', str(rviz_config), '--ros-args', '-r', '__ns:={namespace}', '-r', '__node:=vaf_rviz',
         '-r', '/map:={namespace}/map', '-r', '/tf:={namespace}/tf', '-r', '/tf_static:={namespace}/tf_static', '-r', '/scan:={namespace}/scan'],
        env=ros_env, health=dict(argv=['ros2','node','list'],contains=['{namespace}/vaf_rviz'],timeout_s=2), ready=ros('rviz'),
        connection=dict(kind='ros2', description='RViz node plus live TF data in selected namespace; read-only configuration'),
        requires=[dep('file',rviz_config)], timeout=60)}, permissions=['desktop','ros_read'], dependencies=ros_deps, integrations=['ros2.topics', 'vehicle.context'])
    ros_tool = make('ros2', 'ROS 2 graph observer', 'service', {'default':profile(
        [python, '-u', '-m', 'vehicle_autonomy.app.tools.ros_tools', 'observe'], env=ros_env,
        health=ros('graph'), ready=ros('graph'), connection=dict(kind='ros2', description='Read-only Topic / Service / Action graph observer'))},
        permissions=['ros_read'], dependencies=ros_deps, integrations=['ros2.topics','ros2.services','ros2.actions'])
    nav2_params = root/'simulation/phase5/nav2_rover.yaml'; bt = root/'simulation/phase5/navigate_rover.xml'
    nav2_deps = [*ros_deps]
    # Every native binary must be present. No nav2_bringup package is assumed.
    ament = ros_env.get('AMENT_PREFIX_PATH', '').split(os.pathsep)
    from .ros_tools import NODES
    for package, executable in NODES:
        found = next((Path(prefix)/'lib'/package/executable for prefix in ament if (Path(prefix)/'lib'/package/executable).is_file()), None)
        nav2_deps.append(dep('file',found or Path('/NOT_CONFIGURED/nav2')/package/executable))
    nav2 = make('nav2','Nav2 isolated services','service',{'default':profile(
        [python,'-u','-m','vehicle_autonomy.app.tools.ros_tools','start-nav2','--params',str(nav2_params),'--behavior-tree',str(bt)], env=ros_env,
        health=dict(argv=['ros2','node','list'],contains=['{namespace}/vaf_tools/controller_server'],timeout_s=2), ready=ros('nav2'),
        connection=dict(kind='ros2.action.NavigateToPose', description='Endpoint {namespace}/vaf_tools/navigate_to_pose; isolated cmd_vel, no vehicle authority'),
        requires=[dep('file',nav2_params),dep('file',bt)], timeout=120)}, permissions=['ros_read','ros_service'], dependencies=nav2_deps,
        integrations=['ros2.action.NavigateToPose', 'ros2.lifecycle.GetState'])
    relay = Path(qgc_relay).resolve() if qgc_relay else Path('/NOT_CONFIGURED/telemetry-only-relay.json')
    qgc_profile = profile([str(Path(qgc).resolve()) if qgc else 'QGroundControl', '--appimage-extract-and-run'],
        connection=dict(kind='mavlink.telemetry_only', description='Use only the relay declared in the trusted local deployment; QGC internal settings are not remotely edited', telemetry_only=True),
        requires=[dep('file',relay)])
    # A real file must explicitly attest the one-way relay. Mere file presence
    # does not authorize a bidirectional QGC connection.
    if qgc_relay:
        data = json.loads(relay.read_text())
        if data.get('telemetry_only') is not True or not data.get('description'): raise ValueError('trusted telemetry-only relay declaration required')
        qgc_profile['connection']['description'] = data['description']
    qgc_tool = make('qgroundcontrol','QGroundControl','gui',{'monitor':qgc_profile}, permissions=['desktop','telemetry_only'], integrations=['mavlink.telemetry_only'])
    qgc_tool['process_names']=['QGroundControl','qgroundcontrol']
    partition = 'vaf_tools_' + uuid4().hex[:12]
    world = root/'configs/tools/lab.sdf'
    gz_env = {'GZ_IP':'127.0.0.1','GZ_PARTITION':partition}
    stats = dict(argv=['gz','topic','-e','-n','1','-t','/world/vaf_tool_lab/stats'],contains=['sim_time'],timeout_s=2)
    gazebo = make('gazebo','Gazebo Sim','simulation',{'headless':profile(['gz','sim','-s','-r',str(world)],env=gz_env,
        health=stats, ready=stats, requires=[dep('file',world)], connection=dict(kind='gazebo',description=f'Isolated empty world vaf_tool_lab; partition {partition}. ArduPilot profile requires its plugin and world.'), timeout=30)}, permissions=['simulation'], integrations=['gazebo.stats'])
    if plugin:
        gazebo['dependencies'].append(dep('file',Path(plugin).resolve()))
    sitl_dir = Path(sitl_dir).resolve() if sitl_dir else Path('/NOT_CONFIGURED/sitl')
    sitl_profiles = {}
    for index,(kind,exe,model) in enumerate((('rover','ardurover','rover'),('copter','arducopter','quad'),('plane','arduplane','plane'))):
        port=6460+10*index
        sitl_profiles[kind]=profile([str(sitl_dir/exe), '--model',model,'--speedup','1','--instance',str(70+index),'--base-port',str(port), '--sim-address','127.0.0.1'],
            connection=dict(kind='mavlink.sitl',description=f'Owned native {kind} simulator; loopback TCP {port}. No automatic Arm/motion; not coupled to the empty Gazebo world.'),
            requires=[dep('file',sitl_dir/exe)])
        # SITL TCP listening is queried without making a MAVLink connection.
        sitl_profiles[kind]['health']=dict(argv=[python,'-m','vehicle_autonomy.app.tools.tcp_probe',str(port)],contains=['LISTEN'],timeout_s=1)
        sitl_profiles[kind]['ready']=deepcopy(sitl_profiles[kind]['health'])
    sitl=make('sitl','ArduPilot SITL','simulation',sitl_profiles,permissions=['simulation'],integrations=['mavlink.sitl'])
    return dict(schema=1,tools=[rviz,qgc_tool,gazebo,nav2,ros_tool,sitl])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--ros-wrapper',type=Path)
    p.add_argument('--qgc',type=Path);p.add_argument('--qgc-relay',type=Path);p.add_argument('--sitl-dir',type=Path);p.add_argument('--ardupilot-plugin',type=Path)
    a=p.parse_args();env=None
    if a.ros_wrapper:
        # Explicit local operator-selected environment; fixed argv, no shell
        # interpolation and no environment values sent to the browser.
        result=subprocess.run([str(a.ros_wrapper.resolve()),'/usr/bin/env','-0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,check=True)
        if len(result.stdout)>131072:raise ValueError('ROS environment too large')
        full=dict(part.decode().split('=',1) for part in result.stdout.split(b'\0') if b'=' in part)
        allowed=('PATH','PYTHONPATH','LD_LIBRARY_PATH','AMENT_PREFIX_PATH','COLCON_PREFIX_PATH','ROS_DISTRO','ROS_VERSION','ROS_PYTHON_VERSION','RMW_IMPLEMENTATION','ROS_AUTOMATIC_DISCOVERY_RANGE','ROS_LOCALHOST_ONLY')
        env={k:full[k] for k in allowed if k in full}
    value=registry(ros_env=env,qgc=a.qgc,qgc_relay=a.qgc_relay,sitl_dir=a.sitl_dir,plugin=a.ardupilot_plugin)
    # Never overwrite existing operator configuration.
    a.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with a.output.open('x') as stream:json.dump(value,stream,indent=2)
    os.chmod(a.output,0o600)
    print('Registry created:',a.output)


if __name__=='__main__':raise SystemExit(main())
