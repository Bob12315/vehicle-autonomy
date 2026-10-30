"""Trusted local deployment discovery; no browser-supplied paths or argv."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from vehicle_autonomy.app.tools.builtins import ROS_KEYS,make,profile
from vehicle_autonomy.app.tools.schema import object_fields,manifest
from .desktop import diagnostic
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment

IDS=('gazebo-gui','rviz2','qgroundcontrol')


def configuration(root,path=None):
    value=json.loads(Path(path or Path(root)/'configs/control-center.json').read_text())
    object_fields(value,('schema','qgc_port','ros_wrapper','workspace_setup','tools'))
    if value['schema']!=1 or type(value['qgc_port']) is not int or not 1024<=value['qgc_port']<=65535:raise ValueError('control-center configuration schema/UDP port rejected')
    if set(value['tools'])!=set(IDS):raise ValueError('only registered desktop tools are allowed')
    for key in IDS:
        item=value['tools'][key]
        object_fields(item,('name','executable','args','env','dependencies','health','stop'),('cwd',))
        if item['executable'] is not None and (not isinstance(item['executable'],str) or not Path(item['executable']).is_absolute()):raise ValueError('trusted executable must be an absolute path')
        if item.get('cwd') is not None and (not isinstance(item['cwd'],str) or not Path(item['cwd']).is_absolute()):raise ValueError('trusted cwd must be absolute')
        if item['stop']!='owned_process_group':raise ValueError('only owned tool stop is supported')
        # The existing Manifest validator validates bounded argv/environment.
        make(key,item['name'],'gui',{'default':profile([item['executable'] or '/NOT_FOUND/'+key,*item['args']],env=item['env'])})
    return value


def ros_environment(root,config):
    host=HostEnvironment(root)
    # Optional setup paths are trusted host configuration, never HTTP inputs.
    workspace=config['workspace_setup']
    if config['ros_wrapper']:
        command=[str(Path(config['ros_wrapper']).resolve()),'/usr/bin/env','-0']
        environment=host.process_environment()
    else:
        command,environment=host.ros_command(['/usr/bin/env','-0'],workspace=workspace is None)
    if workspace:
        setup=Path(workspace)
        if not setup.is_absolute() or not setup.is_file():raise ValueError('configured Framework ROS workspace setup is missing')
        wrapped=['/bin/bash','-c','source "$1" >&2 || exit; exec /usr/bin/env -0','vaf-workspace',str(setup)]
        command=([str(Path(config['ros_wrapper']).resolve()),*wrapped] if config['ros_wrapper'] else host.ros_command(wrapped,workspace=False)[0])
    result=subprocess.run(command,env=environment,capture_output=True,timeout=15)
    if result.returncode:raise ValueError(result.stderr.decode(errors='replace')[-600:])
    if len(result.stdout)>131072:raise ValueError('ROS environment too large')
    environment=dict(s.decode().split('=',1) for s in result.stdout.split(b'\0') if b'=' in s)
    return {k:environment[k] for k in ROS_KEYS if k in environment}


def qgc_candidates():
    value=HostEnvironment().executable('qgroundcontrol')
    return [value] if value else []


def inspect_host(root,path=None):
    config=configuration(root,path);ros={};error=None;host=HostEnvironment(root)
    try:ros=ros_environment(root,config)
    except (ValueError,OSError,subprocess.TimeoutExpired) as exc:error=str(exc)
    defaults={'gazebo-gui':host.executable('gazebo'),'rviz2':host.executable('rviz2') or shutil.which('rviz2',path=ros.get('PATH','')),
        'qgroundcontrol':host.executable('qgroundcontrol')}
    tools={}
    for key,item in config['tools'].items():
        binary=item['executable'] or defaults[key]
        tools[key]=dict(name=item['name'],executable=binary,installed=bool(binary and Path(binary).is_file() and os.access(binary,os.X_OK)),
            args=item['args'],dependencies=item['dependencies'],health=item['health'],stop=item['stop'])
    return dict(config=config,tools=tools,ros=ros,ros_error=error,desktop=diagnostic())


def qt_environment(ros):
    environment=dict(ros,QT_QPA_PLATFORM='xcb')
    for prefix in ros.get('AMENT_PREFIX_PATH','').split(':'):
        path=Path(prefix)
        if len(path.parents)<3:continue
        for plugin in (path.parents[2]/'usr/lib').glob('*-linux-gnu/qt5/plugins'):
            if (plugin/'platforms').is_dir():
                environment.update(QT_PLUGIN_PATH=str(plugin),QT_QPA_PLATFORM_PLUGIN_PATH=str(plugin/'platforms'));return environment
    return environment


def definitions(host,source_config):
    result=[];python=sys.executable
    window=dict(argv=[python,'-m','vehicle_autonomy.app.control_center.desktop'],contains=['"status": "READY"'],timeout_s=4)
    for key in IDS:
        item=host['config']['tools'][key];binary=host['tools'][key]['executable'] or '/NOT_FOUND/'+key
        environment=dict(item['env'],QT_QPA_PLATFORM='xcb')
        if key=='rviz2':environment.update(qt_environment(host['ros']))
        command=[binary,*item['args']]
        if key=='qgroundcontrol' and binary.lower().endswith('.appimage'):command.insert(1,'--appimage-extract-and-run')
        permissions=['desktop']+(['telemetry_only'] if key=='qgroundcontrol' else [])
        connection=dict(kind='desktop',description='本机真实窗口；车辆控制继续使用 Framework。')
        if key=='qgroundcontrol':connection.update(kind='mavlink.telemetry_only',telemetry_only=True,description='127.0.0.1:'+str(host['config']['qgc_port'])+'；单向遥测，无 QGC 指令回传。')
        p=profile(command,env=environment,health=window,ready=deepcopy(window),timeout=50,connection=connection)
        if key=='gazebo-gui':
            for probe in ('health','ready'):
                p[probe]=deepcopy(window);p[probe]['argv'].append('--gazebo')
        if item.get('cwd') is not None:p['cwd']=item['cwd']
        if key=='qgroundcontrol':p['exclusive_ports']=[dict(protocol='udp',port=host['config']['qgc_port'])]
        result.append(make(key,item['name'],'gui',{'default':p},permissions=permissions))
    bridge=profile([python,'-u','-m','vehicle_autonomy.app.visualization.worker','--config',str(source_config)],env=host['ros'])
    probe=dict(argv=[python,'-m','vehicle_autonomy.app.visualization.probe','bridge-ready','--config',str(source_config)],contains=['"status": "READY"'],timeout_s=4)
    bridge.update(health=probe,ready=probe,startup_timeout_s=90)
    result.append(make('visualization-bridge','Framework 遥测可视化桥','service',{'default':bridge},permissions=['ros_read']))
    return [manifest(value) for value in result]
