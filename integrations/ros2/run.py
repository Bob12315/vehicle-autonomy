"""Exec an installed ROS executable without leaving a ros2-run parent process."""
import os
import sys
import hashlib
import json
from pathlib import Path


def boundary_overlay(prefix, library):
    """Only the explicitly selected SLAM process receives this exact ABI patch."""
    path=Path(library)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("explicit regular absolute boundary overlay required")
    manifest=json.loads(path.with_name('manifest.json').read_text())
    sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    if manifest.get('schema')!=1 or manifest.get('upstream_version')!='2.8.5' or sha(path)!=manifest['library_sha256']:
        raise ValueError('boundary overlay manifest/content mismatch')
    for name in ('libtoolbox_common.so','libkartoSlamToolbox.so'):
        if sha(Path(prefix)/'lib'/name)!=manifest['runtime_libraries'][name]:
            raise ValueError('boundary overlay runtime ABI changed; rebuild explicitly')
    return str(path)


def main():
    if len(sys.argv) < 3 or any(Path(v).name != v for v in sys.argv[1:3]):
        raise SystemExit("usage: python -m integrations.ros2.run PACKAGE EXECUTABLE [ARGS...]")
    from ament_index_python.packages import get_package_prefix
    package, executable = sys.argv[1:3]
    prefix = Path(get_package_prefix(package))
    path = prefix / "lib" / package / executable
    if package == 'slam_toolbox' and os.environ.get('VAF_SLAM_BOUNDARY_LIBRARY'):
        library=boundary_overlay(prefix,os.environ['VAF_SLAM_BOUNDARY_LIBRARY'])
        os.environ['LD_PRELOAD']=library+(':'+os.environ['LD_PRELOAD'] if os.environ.get('LD_PRELOAD') else '')
    os.execv(path, [str(path), *sys.argv[3:]])


if __name__ == "__main__":
    main()
