"""Build the small public-rclcpp GID adapter in an explicit isolated directory."""
import argparse,hashlib,json,os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


def build(directory):
    from ament_index_python.packages import get_package_prefix
    if sys.byteorder!='little':raise ValueError('native frame ABI has only been qualified for little endian')
    directory=Path(directory).absolute()
    if directory.resolve()!=directory or directory.exists():raise ValueError('fresh native source build directory required')
    directory.mkdir(mode=0o700,parents=True)
    source=Path(__file__).with_name('native')
    for name,command in (('configure',['cmake','-S',str(source),'-B',str(directory)]),('build',['cmake','--build',str(directory),'-j2'])):
        with (directory/(name+'.log')).open('x') as log:
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=120)
        if result.returncode:raise RuntimeError('native source adapter '+name+' failed; inspect '+str(directory/(name+'.log')))
    def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
    binary=directory/'vaf_native_source_receiver';binary.chmod(0o700);prefix=Path(get_package_prefix('rclcpp'))
    manifest=dict(schema=1,binary=str(binary),binary_sha256=sha(binary),native_interface='public rclcpp MessageInfo.get_rmw_message_info().publisher_gid',wire_abi='little-endian-v1-164-bytes',sources={p.name:sha(p) for p in source.iterdir() if p.is_file()},packages={name:ET.parse(Path(get_package_prefix(name))/'share'/name/'package.xml').findtext('version') for name in ('rclcpp','rmw','geometry_msgs')},runtime_libraries={p.name:sha(p) for p in (prefix/'lib/librclcpp.so',prefix/'lib/librmw_fastrtps_cpp.so')})
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True,type=Path);a=p.parse_args();print(json.dumps(build(a.directory)))
