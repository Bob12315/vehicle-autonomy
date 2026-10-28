"""Extend an operator-selected Registry with matching real-data profiles."""
from copy import deepcopy
from pathlib import Path
import platform
import sys

from vehicle_autonomy._resources import resource_root
from .config import load


def configure(value,path,ros_env,*,owned_simulation=None):
    from vehicle_autonomy.app.tools.builtins import make,profile
    config=load(path);path=str(Path(path).resolve());value=deepcopy(value);root=resource_root();python=sys.executable
    ros_env=dict(ros_env)
    # Qt platform plugins are scoped to RViz, never to the vehicle/ROS bridge.
    gui_env=dict(ros_env)
    architecture=platform.machine();triplet={'x86_64':'x86_64-linux-gnu','aarch64':'aarch64-linux-gnu'}.get(architecture)
    for prefix in ros_env.get('AMENT_PREFIX_PATH','').split(':'):
        if not prefix or not triplet:continue
        extracted=Path(prefix)
        if len(extracted.parents)<3:continue
        plugins=extracted.parents[2]/'usr/lib'/triplet/'qt5/plugins'
        if (plugins/'platforms').is_dir():
            gui_env.update(QT_PLUGIN_PATH=str(plugins),QT_QPA_PLATFORM_PLUGIN_PATH=str(plugins/'platforms'));break
    deps=[dict(kind='file',value=path),dict(kind='file',value=config['token_file'])]
    ros_deps=[dict(kind='executable',value='ros2'),dict(kind='environment',value='ROS_DISTRO')]
    def probe(operation):return dict(argv=[python,'-m','vehicle_autonomy.app.visualization.probe',operation,'--config',path],contains=['"status": "READY"'],timeout_s=4)
    bridge_profiles={};rviz=next(t for t in value['tools'] if t['id']=='rviz2');rviz['integrations'].append('ros2.visualization')
    for kind in ('rover','copter','plane'):
        base=dict(ros_env,VAF_VISUALIZATION_KIND=kind);desktop=dict(gui_env,VAF_VISUALIZATION_KIND=kind)
        bridge_profiles[kind]=profile([python,'-u','-m','vehicle_autonomy.app.visualization.worker','--config',path],env=base,
            health=probe('bridge-health'),ready=probe('bridge-ready'),requires=deps,timeout=90,
            connection=dict(kind='ros2.visualization',endpoint='{namespace}/viz/odometry',description='Fresh Framework ENU pose, bounded actual trajectory, GPS and isolated TF; proposals only, no vehicle authority'))
        rviz['profiles'][kind]=profile([python,'-u','-m','vehicle_autonomy.app.visualization.rviz','--config',path],env=desktop,
            health=probe('rviz-health'),ready=probe('rviz-ready'),requires=deps+[dict(kind='file',value=str(root/f'configs/rviz/{kind}-visualization.rviz')),dict(kind='executable',value='rviz2')],timeout=90,
            connection=dict(kind='ros2.visualization',endpoint='{namespace}/viz/markers',description='Native desktop RViz with fresh matching vehicle TF/pose and actual marker/path subscriptions; optional external layers require calibrated bindings'))
    value['tools'].append(make('visualization-bridge','Framework Visualization Bridge','service',bridge_profiles,
        permissions=['ros_read'],dependencies=ros_deps,integrations=['vehicle.context','ros2.visualization','pending.goal']))
    if owned_simulation is not None:
        manifest=str(Path(owned_simulation).resolve())
        for component in ('gazebo','sitl'):
            tool=next(t for t in value['tools'] if t['id']==component);tool['integrations'].append('ros2.visualization')
            command=[python,'-u','-m','vehicle_autonomy.app.visualization.simulation']
            args=['--component',component,'--manifest',manifest,'--config',path]
            check=dict(argv=command+['probe']+args,contains=['"status": "READY"'],timeout_s=2)
            tool['profiles']['framework-owned']=profile(command+['watch']+args,env=ros_env,health=check,ready=check,
                requires=deps+[dict(kind='file',value=manifest)],connection=dict(kind='framework.simulation.observer',description='Observe current matching Framework-owned process epochs and typed source; no simulator launch/kill and no vehicle commands'))
    return value
