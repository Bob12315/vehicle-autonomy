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
import xml.etree.ElementTree as ET

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment
from .schema import manifest

ROS_KEYS=('PATH','PYTHONPATH','LD_LIBRARY_PATH','AMENT_PREFIX_PATH','COLCON_PREFIX_PATH','ROS_DISTRO','ROS_VERSION','ROS_PYTHON_VERSION','RMW_IMPLEMENTATION','ROS_AUTOMATIC_DISCOVERY_RANGE','ROS_LOCALHOST_ONLY')


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
    root = resource_root(); ros_env = {k:os.environ[k] for k in ROS_KEYS if k in os.environ} if ros_env is None else ros_env
    host = HostEnvironment(root)
    qgc = qgc if qgc is not None else host.executable('qgroundcontrol')
    sitl_dir = sitl_dir if sitl_dir is not None else host.path('ardupilot_root')/'build/sitl/bin'
    python = sys.executable
    ros = lambda op: dict(argv=[python, '-m', 'vehicle_autonomy.app.tools.ros_tools', op], contains=['"status": "READY"'], timeout_s=3)
    dep = lambda kind, value: dict(kind=kind, value=str(value))
    ros_deps = [dep('executable','ros2'), dep('environment','ROS_DISTRO')]
    rviz_config = root/'configs/rviz/navigation-readonly.rviz'
    rviz = make('rviz2', 'RViz2', 'gui', {'default':profile(
        [host.executable('rviz2') or 'rviz2', '-d', str(rviz_config), '--ros-args', '-r', '__ns:={namespace}', '-r', '__node:=vaf_rviz',
         '-r', '/map:={namespace}/map', '-r', '/tf:={namespace}/tf', '-r', '/tf_static:={namespace}/tf_static', '-r', '/scan:={namespace}/scan'],
        env=ros_env, health=ros('rviz-node'), ready=ros('rviz'),
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
        health=ros('nav2-nodes'), ready=ros('nav2'),
        connection=dict(kind='ros2.action.NavigateToPose',endpoint='{namespace}/vaf_tools/navigate_to_pose', description='Endpoint {namespace}/vaf_tools/navigate_to_pose; isolated cmd_vel, no vehicle authority'),
        requires=[dep('file',nav2_params),dep('file',bt)], timeout=120)}, permissions=['ros_read','ros_service'], dependencies=nav2_deps,
        integrations=['ros2.action.NavigateToPose', 'ros2.lifecycle.GetState'])
    relay = Path(qgc_relay).resolve() if qgc_relay else Path('/NOT_CONFIGURED/telemetry-only-relay.json')
    qgc_command=[str(Path(qgc).resolve()) if qgc else 'QGroundControl']
    if qgc and str(qgc).lower().endswith('.appimage'):qgc_command.append('--appimage-extract-and-run')
    qgc_profile = profile(qgc_command,
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
    stats = dict(argv=[HostEnvironment(root).executable('gazebo') or 'gz','topic','-e','-n','1','-t','/world/vaf_tool_lab/stats'],contains=['sim_time'],timeout_s=2)
    gazebo = make('gazebo','Gazebo Sim','simulation',{'headless':profile([HostEnvironment(root).executable('gazebo') or 'gz','sim','-s','-r',str(world)],env=gz_env,
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
        sitl_profiles[kind]['exclusive_ports']=[dict(protocol='tcp',port=port+offset) for offset in (0,2,3)]
    sitl=make('sitl','ArduPilot SITL','simulation',sitl_profiles,permissions=['simulation'],integrations=['mavlink.sitl'])
    return dict(schema=1,tools=[rviz,qgc_tool,gazebo,nav2,ros_tool,sitl])


def coupled_rover(value,output,sitl_dir,plugin,instance=70):
    """Materialize matching owned deployment resources, never edit source worlds."""
    if sitl_dir is None or plugin is None:raise ValueError('coupled Rover requires explicit SITL directory and ArduPilot plugin')
    root=resource_root();binary=Path(sitl_dir).resolve()/'ardurover';plugin=Path(plugin).resolve()
    inputs=[binary,plugin,root/'simulation/models/target_rover/model.sdf',root/'simulation/worlds/rover_runway.sdf']
    for source in inputs:
        if not source.is_file():raise ValueError('coupled Rover dependency missing: '+str(source))
    directory=output.parent.resolve()/('rover-coupled-'+uuid4().hex[:10]);directory.mkdir(mode=0o700)
    model=ET.parse(inputs[2]);model.find('.//fdm_port_in').text=str(9002+instance*10)
    model_path=directory/'model.sdf';model.write(model_path,encoding='unicode')
    world=ET.parse(inputs[3]);name='vaf_rover_'+uuid4().hex[:10];world.find('world').set('name',name)
    world.find('.//include/uri').text=model_path.as_uri();world_path=directory/'world.sdf';world.write(world_path,encoding='unicode')
    gazebo=next(t for t in value['tools'] if t['id']=='gazebo');sitl=next(t for t in value['tools'] if t['id']=='sitl')
    env={'GZ_IP':'127.0.0.1','GZ_PARTITION':name,'GZ_SIM_RESOURCE_PATH':str(root/'simulation/models'),'GZ_SIM_SYSTEM_PLUGIN_PATH':str(plugin.parent)}
    stats=dict(argv=[HostEnvironment(root).executable('gazebo') or 'gz','topic','-e','-n','1','-t',f'/world/{name}/stats'],contains=['sim_time'],timeout_s=2)
    gazebo['profiles']['rover-coupled']=profile([HostEnvironment(root).executable('gazebo') or 'gz','sim','-s','-r',str(world_path)],env=env,health=stats,ready=stats,
        connection=dict(kind='gazebo.ardupilot',description=f'Actual target_rover world {name}, loopback JSON FDM {9002+instance*10}; paired with SITL rover-coupled'),
        requires=[dict(kind='file',value=str(p)) for p in (world_path,model_path,plugin)],timeout=40)
    gazebo['profiles']['rover-coupled']['exclusive_ports']=[dict(protocol='udp',port=9002+instance*10)]
    params=root/'simulation/params/rover_phase2_rtl.parm'
    defaults=Path(sitl_dir).resolve().parents[2]/'Tools/autotest/default_params'
    parameter_files=[defaults/'rover.parm',defaults/'rover-skid.parm',root/'simulation/params/rover_telemetry.parm',params]
    for path in parameter_files:
        if not path.is_file():raise ValueError('trusted Rover defaults missing: '+str(path))
    p=deepcopy(sitl['profiles']['rover']);p['argv']=[str(binary),'--model','JSON','--speedup','1','--instance',str(instance),'--base-port','6460','--sim-address','127.0.0.1','--defaults',','.join(map(str,parameter_files))]
    p['requires']=[dict(kind='file',value=str(f)) for f in [binary,*parameter_files]]
    p['connection']=dict(kind='mavlink.sitl',description=f'Coupled target_rover: loopback TCP 6460, JSON FDM {9002+instance*10}; requires matching Gazebo rover-coupled. No signing/vehicle authority provisioned.')
    sitl['profiles']['rover-coupled']=p
    for item in value['tools']:manifest(item)
    return value


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--ros-wrapper',type=Path)
    p.add_argument('--qgc',type=Path);p.add_argument('--qgc-relay',type=Path);p.add_argument('--sitl-dir',type=Path);p.add_argument('--ardupilot-plugin',type=Path)
    p.add_argument('--coupled-rover',action='store_true',help='generate matching isolated Rover Gazebo/JSON SITL deployment profiles')
    p.add_argument('--visualization-config',type=Path,help='trusted narrow Framework feed config; adds matching bridge and three RViz profiles')
    p.add_argument('--owned-simulation',type=Path,help='with visualization-config: public current Framework simulation manifest for non-owning Workspace dependencies')
    a=p.parse_args();env=None;host=HostEnvironment()
    if a.ros_wrapper:
        # Explicit local operator-selected environment; fixed argv, no shell
        # interpolation and no environment values sent to the browser.
        result=subprocess.run([str(a.ros_wrapper.resolve()),'/usr/bin/env','-0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,check=True)
        if len(result.stdout)>131072:raise ValueError('ROS environment too large')
        full=dict(part.decode().split('=',1) for part in result.stdout.split(b'\0') if b'=' in part)
        env={k:full[k] for k in ROS_KEYS if k in full}
    else:
        try:
            command,environment=host.ros_command(['/usr/bin/env','-0'])
        except ValueError:
            if any(key in host.values['paths'] for key in ('ros2_root','ros2_setup','ros2_workspace')) or os.environ.get('VAF_ROS2_ROOT'):
                raise
        else:
            result=subprocess.run(command,env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,check=True)
            if len(result.stdout)>131072:raise ValueError('ROS environment too large')
            full=dict(part.decode().split('=',1) for part in result.stdout.split(b'\0') if b'=' in part)
            env={k:full[k] for k in ROS_KEYS if k in full}
    if a.coupled_rover:
        a.sitl_dir=a.sitl_dir or host.path('ardupilot_root')/'build/sitl/bin'
        a.ardupilot_plugin=a.ardupilot_plugin or host.path('gazebo_plugin_root')/'build/libArduPilotPlugin.so'
    value=registry(ros_env=env,qgc=a.qgc,qgc_relay=a.qgc_relay,sitl_dir=a.sitl_dir,plugin=a.ardupilot_plugin)
    if a.visualization_config:
        from vehicle_autonomy.app.visualization.registry import configure
        value=configure(value,a.visualization_config,env or {k:os.environ[k] for k in ROS_KEYS if k in os.environ},owned_simulation=a.owned_simulation)
    elif a.owned_simulation:p.error('--owned-simulation requires --visualization-config')
    # Never overwrite existing operator configuration.
    a.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if a.output.exists():raise ValueError('registry exists; select a new output, existing configuration is never overwritten')
    if a.coupled_rover:value=coupled_rover(value,a.output,a.sitl_dir,a.ardupilot_plugin)
    with a.output.open('x') as stream:json.dump(value,stream,indent=2)
    os.chmod(a.output,0o600)
    print('Registry created:',a.output)


if __name__=='__main__':raise SystemExit(main())
