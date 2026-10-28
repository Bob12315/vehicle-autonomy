"""Render a trusted vehicle profile and exec the native desktop RViz2."""
import argparse
import os
from pathlib import Path
import shutil

from vehicle_autonomy._resources import resource_root
from .config import frames,load,vehicle_context


def render(ctx,config):
    names=frames(ctx,config);ns=names['namespace'];external=config.get('external')
    source=(resource_root()/f"configs/rviz/{ctx['vehicle_type']}-visualization.rviz").read_text()
    values={'FIXED':names['fixed'],'ODOM':names['odom'],'BASE':names['base'],'TOPIC':names['topic'],
        'SIM_TIME':'true' if config.get('use_sim_time') else 'false'}
    defaults=dict(scan=ns+'/scan',points=ns+'/points',map=ns+'/map',global_path=ns+'/plan',local_path=ns+'/local_plan',global_costmap=ns+'/global_costmap/costmap',local_costmap=ns+'/local_costmap/costmap',perception=ns+'/perception/markers')
    for key,value in defaults.items():
        configured=None if external is None else external['topics'].get(key)
        values[key.upper()]=configured or value;values[key.upper()+'_ENABLED']='true' if configured else 'false'
    for key,value in values.items():source=source.replace('__'+key+'__',value)
    if '__' in source:raise ValueError('unresolved trusted RViz profile binding')
    return source,names


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')) or os.environ.get('QT_QPA_PLATFORM') in ('offscreen','minimal'):raise ValueError('a real desktop display is required for Open RViz2')
    config=load(a.config);ctx=vehicle_context();source,names=render(ctx,config)
    path=Path.cwd()/'vehicle-visualization.rviz';path.write_text(source)
    binary=shutil.which('rviz2')
    if binary is None:raise ValueError('RViz2 is not installed in the selected ROS environment')
    print('Opening native RViz2 / '+ctx['vehicle_type']+' / '+ctx['vehicle_id']+'; goals are proposals only',flush=True)
    command=[binary,'-d',str(path),'--ros-args','-r','__ns:='+(names['namespace'] or '/'),'-r','__node:=vaf_rviz',
        '-r','/tf:='+names['tf'],'-r','/tf_static:='+names['tf_static'],'-r','/goal_pose:='+names['topic']+'/pending_goal',
        '-p','use_sim_time:='+('true' if config.get('use_sim_time') else 'false')]
    os.execv(binary,command)


if __name__=='__main__':main()
