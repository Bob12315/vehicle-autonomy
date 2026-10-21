"""Prepare authenticated Humble ARM64 packages without installing system packages.

Run on the Internet-connected PC with the RK3588's /var/lib/dpkg/status copy.
Transfer root/ to the board; use with_ros2_humble.sh there. No maintainer scripts,
host architecture changes, system apt sources or vehicle connections are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROS_KEY = 'C1CF6E31E6BADE8868B172B4F42ED6FBAB17C654'
PACKAGES = ['ros-humble-rclpy', 'ros-humble-sensor-msgs-py', 'ros-humble-tf2-ros-py',
            'ros-humble-ros2cli', 'ros-humble-ros2run', 'ros-humble-ros2topic',
            'ros-humble-ros2bag', 'ros-humble-rosbag2-storage-default-plugins',
            'ros-humble-slam-toolbox', 'ros-humble-nav2-planner',
            'ros-humble-nav2-smac-planner', 'ros-humble-nav2-amcl',
            'ros-humble-nav2-map-server', 'ros-humble-nav2-lifecycle-manager', 'libpcap0.8-dev',
            'ros-humble-navigation2', 'ros-humble-nav2-bringup', 'ros-humble-robot-localization',
            'ros-humble-ros2launch',
            # Target has an ICU build from jammy-proposed without matching dev files.
            # Use the signed stable runtime AND dev files only inside this prefix.
            'libicu70=70.1-2']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--status-file', required=True, type=Path,
                        help='unmodified dpkg status copied from Ubuntu 22.04 ARM64 target')
    parser.add_argument('--os-release-file', required=True, type=Path,
                        help='target /etc/os-release copy')
    parser.add_argument('--visualization', action='store_true', help='also extract RViz2 for the board ROS host')
    args = parser.parse_args()
    status = args.status_file.resolve()
    text = status.read_text()
    release = dict(line.split('=', 1) for line in args.os_release_file.read_text().splitlines()
                   if '=' in line and not line.startswith('#'))
    if release.get('ID', '').strip('"') != 'ubuntu' or release.get('VERSION_ID', '').strip('"') != '22.04':
        parser.error('target must be Ubuntu 22.04 Jammy')
    if 'Architecture: arm64' not in text or 'Package: libc6\n' not in text:
        parser.error('target ARM64 dpkg status required')
    directory = args.directory.resolve()
    apt = directory / 'apt'
    for item in ('lists/partial', 'archives/partial', 'gnupg'):
        (apt / item).mkdir(mode=0o700, parents=True, exist_ok=True)
    key = apt / 'ros.gpg'
    subprocess.run(['curl', '-fsSL', '--connect-timeout', '10', '--max-time', '60',
                    'https://raw.githubusercontent.com/ros/rosdistro/master/ros.key',
                    '-o', str(key)], check=True)
    keys = subprocess.check_output(['gpg', '--homedir', str(apt/'gnupg'), '--show-keys',
                                    '--with-colons', str(key)], text=True)
    if ROS_KEY not in [line.split(':')[9] for line in keys.splitlines() if line.startswith('fpr:')]:
        raise RuntimeError('unreviewed ROS signing key')
    sources = apt / 'sources.list'
    sources.write_text(f'deb [arch=arm64 signed-by={key}] https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu jammy main\n' +
        ''.join(f'deb [arch=arm64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] https://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports {suite} main universe restricted multiverse\n'
                for suite in ('jammy', 'jammy-updates', 'jammy-security')))
    config = apt / 'apt.conf'
    config.write_text(f'''APT::Architecture "arm64";
APT::Architectures {{ "arm64"; }};
Dir::Etc::sourcelist "{sources}";
Dir::Etc::sourceparts "-";
Dir::Etc::parts "-";
Dir::State::status "{status}";
Dir::State::lists "{apt/'lists'}";
Dir::Cache::archives "{apt/'archives'}";
Dir::Cache::pkgcache "{apt/'pkgcache.bin'}";
Dir::Cache::srcpkgcache "{apt/'srcpkgcache.bin'}";
Debug::NoLocking "true";
APT::Sandbox::User "{os.environ['USER']}";
Acquire::Retries "2";
Acquire::https::Timeout "30";
Acquire::Languages "none";
''')
    subprocess.run(['apt-get', '-c', str(config), 'update'], check=True)
    requested=PACKAGES+(['ros-humble-rviz2'] if args.visualization else [])
    subprocess.run(['apt-get', '-c', str(config), '--download-only', '--allow-downgrades', '--assume-yes',
                    '--no-install-recommends', 'install', *requested], check=True)
    packages = []
    for archive in sorted((apt/'archives').glob('*.deb')):
        package = subprocess.check_output(['dpkg-deb', '-f', str(archive), 'Package'], text=True).strip()
        arch = subprocess.check_output(['dpkg-deb', '-f', str(archive), 'Architecture'], text=True).strip()
        if arch not in ('all', 'arm64'):
            raise RuntimeError('foreign binary in ARM64 bundle: ' + archive.name)
        # A new libc in LD_LIBRARY_PATH can break the board's existing loader.
        if package in ('libc6', 'libc-bin', 'systemd', 'udev'):
            raise RuntimeError('system runtime upgrade requires a separate container/toolchain: ' + package)
        subprocess.run(['dpkg-deb', '--extract', str(archive), str(directory/'root')], check=True)
        packages.append({'file': archive.name, 'package': package, 'architecture': arch,
                         'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()})
    (directory/'manifest.json').write_text(json.dumps({'distribution': 'humble', 'architecture': 'arm64',
        'key': ROS_KEY, 'requested': requested, 'target_os': release,
        'status_sha256': hashlib.sha256(status.read_bytes()).hexdigest(),
        'packages': packages}, indent=2))
    print('Prepared isolated target prefix:', directory/'root')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
