"""Explicit, checksum-pinned external SLAM software. No install or ROS import."""
import hashlib,json
from pathlib import Path

from .host_environment import HostEnvironment


ARTIFACTS={'sensor':'ws/install/lib/liblivox_gz_sim.so',
           'fast_lio':'ws/install/lib/fast_lio/fastlio_mapping','pgo':'ws/install/lib/sc_pgo/alaserPGO',
           'relocalization':'relocation-runtime/fast_lio_localization/global_localization.py'}
FEATURE_PATCHES={'sensor':('patches/livox-gz-sim-domain-context.patch',),
    'fast_lio':('patches/fast-lio-jazzy-build.patch',),'pgo':('patches/sc-pgo-build.patch',),
    'relocalization':('patches/relocalization-io.patch',)}
FEATURE_SOURCES={'sensor':('livox_gz_sim','livox_messages'),'fast_lio':('fast_lio','ikd_tree','livox_messages'),
    'pgo':('sc_pgo','gtsam','pcl_conversions','pcl_msgs'),'relocalization':('relocalization',)}


def checked(root,feature):
    if feature not in ARTIFACTS:raise ValueError('unknown SLAM dependency')
    base=HostEnvironment(root).path('mid360_slam_root')
    if base is None:raise ValueError('configure HostEnvironment mid360_slam_root first')
    manifest=json.loads((base/'build-manifest.json').read_text())
    lock=json.loads((Path(root)/'simulation/dependencies/mid360-slam.lock.json').read_text())
    certificate=manifest.get('builds',{}).get(feature,{})
    required=FEATURE_SOURCES[feature]
    if any(certificate.get('sources',{}).get(k)!=lock['dependencies'][k]['commit'] for k in required):
        raise ValueError('SLAM source lock mismatch')
    path=base/ARTIFACTS[feature]
    if path.resolve()!=path or not path.is_file():raise ValueError('missing or symlinked SLAM artifact')
    actual=hashlib.sha256(path.read_bytes()).hexdigest()
    if certificate.get('sha256')!=actual:raise ValueError('SLAM binary checksum mismatch')
    for patch in FEATURE_PATCHES[feature]:
        actual=hashlib.sha256((Path(root)/'simulation/dependencies'/patch).read_bytes()).hexdigest()
        if certificate.get('patches',{}).get(patch)!=actual:raise ValueError('SLAM build patch mismatch')
    return base,path,manifest


def ros_environment(root):
    from vehicle_autonomy.app.control_center.registry import ros_environment as environment,configuration
    base,_,_=checked(root,'sensor')
    config=configuration(root);config['workspace_setup']=str(base/'ws/install/setup.bash')
    env=environment(root,config)
    env['LD_LIBRARY_PATH']=str(base/'gtsam-install/lib')+':'+str(base/'deps/root/usr/lib/x86_64-linux-gnu')+':'+str(base/'deps/root/usr/lib')+':'+env.get('LD_LIBRARY_PATH','')
    return env


def server_environment(root,environment):
    # System Gazebo stays authoritative over vendor copies of its own ABI.
    ros=ros_environment(root);env=dict(environment);env.update(ros)
    paths=[p for p in ros.get('LD_LIBRARY_PATH','').split(':') if '/opt/gz_' not in p]
    env['LD_LIBRARY_PATH']=':'.join(['/usr/lib/x86_64-linux-gnu',*paths])
    env.update(ROS_LOCALHOST_ONLY='1',ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',RMW_IMPLEMENTATION='rmw_fastrtps_cpp')
    return env
