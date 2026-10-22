"""Build a pinned, opt-in native occupancy-boundary overlay; never replace ROS files."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

HEADER_SHA256='277fd3ddbb4c655408660e7bab8ff39f49875af709bd7a83ff3d029190d44052'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(directory):
    from ament_index_python.packages import get_package_prefix
    prefix=Path(get_package_prefix('slam_toolbox'))
    if ET.parse(prefix/'share/slam_toolbox/package.xml').findtext('version') != '2.8.5':
        raise ValueError('boundary overlay is audited only for SLAM Toolbox 2.8.5')
    if sha(prefix/'include/karto_sdk/Karto.h') != HEADER_SHA256:
        raise ValueError('unreviewed Karto SDK header; review and rebuild the overlay explicitly')
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    shutil.copytree(prefix/'include/karto_sdk',directory/'karto_sdk')
    header=directory/'karto_sdk/Karto.h';source=header.read_text()
    for axis in ('Width','Height'):
        old=f'static_cast<kt_int32s>(math::Round(size.Get{axis}() * scale))'
        if source.count(old)!=1:raise ValueError('upstream dimension expression changed')
        source=source.replace(old,f'static_cast<kt_int32s>(ceil(size.Get{axis}() * scale)) + 1')
    header.write_text(source)
    native=Path(__file__).with_name('native')
    include=['-I'+str(prefix/'include'),'-I/usr/include/eigen3','-I'+str(prefix.parents[2]/'usr/include')]+[
        '-I'+str(p) for p in (prefix/'include').iterdir() if p.is_dir()]
    common=['g++','-std=c++17','-O2','-fPIC',*include,'-L'+str(prefix/'lib'),
        '-Wl,-rpath,'+str(prefix/'lib')]
    link=['-lkartoSlamToolbox','-lboost_serialization']
    def compile(extra,src,out):
        result=subprocess.run([*common[:4],*extra,*common[4:],str(src),*link,'-o',str(out)],capture_output=True,text=True,timeout=120)
        if result.returncode:raise RuntimeError(result.stderr[-6000:])
    library=directory/'libvaf_slam_boundary.so'
    compile(['-shared','-I'+str(directory)],native/'slam_boundary.cpp',library)
    probes={}
    for name,extra,expected in (('upstream',[],1),('fixed',['-I'+str(directory)],0)):
        binary=directory/name;compile(extra,native/'boundary_test.cpp',binary)
        result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
        if result.returncode!=expected:raise RuntimeError(f'boundary regression {name}: {result.stdout} {result.stderr}')
        probes[name]=json.loads(next(l for l in result.stdout.splitlines() if l.startswith('{')))
    manifest={'schema':1,'upstream_version':'2.8.5','upstream_commit':'ec8f7635dea317b531c419f798f87d90a336f32e',
        'header_sha256':HEADER_SHA256,'patched_header_sha256':sha(header),'library_sha256':sha(library),
        'runtime_libraries':{name:sha(prefix/'lib'/name) for name in ('libtoolbox_common.so','libkartoSlamToolbox.so')},
        'sources':{p.name:sha(p) for p in native.iterdir() if p.is_file()},'native_probes':probes}
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return library,manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
    a=p.parse_args();library,manifest=build(a.output_dir)
    print(json.dumps({'library':str(library),**manifest}))


if __name__=='__main__':main()
