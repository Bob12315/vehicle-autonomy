"""Trusted instance binding of unchanged FAST-LIO estimation parameters."""
from copy import deepcopy
import json
from pathlib import Path


OUTPUTS={'/Odometry':'odometry_raw','/cloud_registered':'registered_raw',
         '/cloud_registered_body':'body_raw','/cloud_effected':'effected_raw',
         '/Laser_map':'local_map_raw','/path':'path_raw','/vaf_input_timing':'input_timing',
         '/tf':'algorithm_tf','/tf_static':'algorithm_tf_static'}


def configure(root,sensor,directory):
    if sensor['backend']!='livox-gz-sliced-pattern-v1':raise ValueError('LIO requires actual sliced capture times; uniform snapshots are not deskew qualification input')
    if any(sensor['mount'][3:]) or any(sensor['imu_in_lidar'][3:]):raise ValueError('this audited sensor/IMU rotation configuration must be aligned')
    ns=sensor['namespace'];parameters=json.loads((Path(root)/'configs/mid360-fast-lio.json').read_text())
    if sensor.get('kind')=='copter':
        override=json.loads((Path(root)/'configs/mid360-fast-lio-copter.json').read_text())
        if set(override)!={'filter_size_surf','filter_size_map'} or any(type(v) not in (int,float) or not .1<=v<=.5 for v in override.values()):
            raise ValueError('audited Copter surface/map voxels required')
        parameters.update(override)
    parameters['common'].update(lid_topic=ns+'/custom',imu_topic=ns+'/imu')
    path=Path(directory)/'fast-lio.yaml'
    path.write_text(json.dumps({'/**':{'ros__parameters':parameters}},indent=2)+'\n')
    args=['-r','__ns:='+ns+'/slam','-r','__node:=vaf_fast_lio']
    for source,target in OUTPUTS.items():args+=['-r',source+':='+ns+'/slam/'+target]
    return path,args,deepcopy(parameters)
