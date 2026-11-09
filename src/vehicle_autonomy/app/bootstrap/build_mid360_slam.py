"""Explicit application-owned external build; never invoked by normal startup.

Source preparation and interface-only patches are documented in the goal-two
dependency record. This command never installs into /usr or starts a driver.
"""
import argparse,hashlib,json,subprocess
from pathlib import Path
from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment
from vehicle_autonomy.app.bootstrap.mid360_slam_environment import ARTIFACTS,FEATURE_PATCHES,FEATURE_SOURCES


def build(feature):
    root=resource_root();host=HostEnvironment(root);base=host.path('mid360_slam_root')
    if base is None:raise ValueError('configure external mid360_slam_root')
    ros=host.path('ros2_root');dev=base/'deps/root/usr';lib=ros/'usr/lib/x86_64-linux-gnu'
    lock=json.loads((root/'simulation/dependencies/mid360-slam.lock.json').read_text())
    sources=dict(fast_lio=base/'ws/src/FAST_LIO_ROS2',ikd_tree=base/'ws/src/FAST_LIO_ROS2/include/ikd-Tree',
        livox_gz_sim=base/'ws/src/livox_gz_sim',livox_messages=base/'livox-message-source',
        pcl_conversions=base/'ws/src/perception_pcl',pcl_msgs=base/'ws/src/pcl_msgs',gtsam=base/'gtsam-source',
        sc_pgo=base/'ws/src/sc_pgo',relocalization=base/'relocation-upstream')
    for key,path in sources.items():
        actual=subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip()
        if actual!=lock['dependencies'][key]['commit']:raise ValueError('dependency HEAD mismatch: '+key)
    for key,patch in (('fast_lio','fast-lio-jazzy-build.patch'),('livox_gz_sim','livox-gz-sim-domain-context.patch'),
        ('sc_pgo','sc-pgo-build.patch')):
        actual=subprocess.check_output(['git','-C',str(sources[key]),'diff','HEAD','--'])
        if actual!=(root/'simulation/dependencies/patches'/patch).read_bytes():raise ValueError('unrecorded external source patch: '+key)
    runtime=base/'relocation-runtime'
    if runtime.exists():
        actual=subprocess.check_output(['git','-C',str(runtime),'diff','HEAD','--'])
        if actual!=(root/'simulation/dependencies/patches/relocalization-io.patch').read_bytes():raise ValueError('unrecorded relocalization I/O patch')
    for name in ('CustomMsg.msg','CustomPoint.msg'):
        if (base/'ws/src/livox_ros_driver2/msg'/name).read_bytes()!=(sources['livox_messages']/'msg'/name).read_bytes():raise ValueError('Livox interface changed')
    packages={'sensor':['livox_ros_driver2','livox_gz_sim'],'fast_lio':['pcl_msgs','pcl_conversions','fast_lio'],'pgo':['sc_pgo'],'relocalization':[]}[feature]
    flags='-Wl,--disable-new-dtags -L'+str(lib)+' -L'+str(dev/'lib/x86_64-linux-gnu')+' -L'+str(dev/'lib')
    python=base/'build-venv/bin/python'
    args=[str(base/'build-venv/bin/colcon'),'build','--merge-install','--executor','sequential',
        '--packages-select',*packages,'--cmake-clean-cache','--cmake-args','-DBUILD_TESTING=OFF',
        '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_PREFIX_PATH='+str(dev)+';'+str(base/'gtsam-install')+';'+str(base/'ws/install'),
        '-DPCL_DIR='+str(dev/'lib/x86_64-linux-gnu/cmake/pcl'),
        '-DBoost_DIR='+str(dev/'lib/x86_64-linux-gnu/cmake/Boost-1.83.0'),
        '-DCMAKE_EXE_LINKER_FLAGS='+flags,'-DCMAKE_SHARED_LINKER_FLAGS='+flags,
        '-DPython3_EXECUTABLE='+str(python),'-DPYTHON_EXECUTABLE='+str(python),
        '-DCMAKE_INSTALL_RPATH='+';'.join(map(str,(dev/'lib/x86_64-linux-gnu',dev/'lib',base/'ws/install/lib',ros/'opt/ros/jazzy/lib',lib)))]
    command,env=host.ros_command(args);env['MAKEFLAGS']='-j1'
    env['LD_LIBRARY_PATH']=str(dev/'lib/x86_64-linux-gnu')+':'+str(dev/'lib')+':'+env.get('LD_LIBRARY_PATH','')
    if packages:subprocess.run(command,env=env,cwd=base/'ws',check=True)
    else:
        subprocess.run([str(python),'-m','py_compile',str(base/ARTIFACTS[feature])],check=True)
    previous=json.loads((base/'build-manifest.json').read_text()) if (base/'build-manifest.json').exists() else {}
    manifest=dict(schema=1,sources={k:v['commit'] for k,v in lock['dependencies'].items()},
        patches={p:hashlib.sha256((root/'simulation/dependencies'/p).read_bytes()).hexdigest() for p in lock['patches']},artifacts={})
    for relative in ('ws/install/lib/liblivox_gz_sim.so','ws/install/lib/fast_lio/fastlio_mapping','ws/install/lib/sc_pgo/alaserPGO',
        'relocation-runtime/fast_lio_localization/global_localization.py'):
        p=base/relative
        if p.is_file():manifest['artifacts'][relative]=hashlib.sha256(p.read_bytes()).hexdigest()
    manifest['builds']=previous.get('builds',{})
    manifest['builds'][feature]=dict(sources={k:lock['dependencies'][k]['commit'] for k in FEATURE_SOURCES[feature]},
        patches={p:manifest['patches'][p] for p in FEATURE_PATCHES[feature]},sha256=manifest['artifacts'][ARTIFACTS[feature]])
    (base/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('feature',choices=tuple(ARTIFACTS));a=p.parse_args();build(a.feature)
