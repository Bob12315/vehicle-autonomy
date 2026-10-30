"""Explicit read-only RViz entry using the common host software index."""
import argparse
import os
from pathlib import Path

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('view', nargs='?', default='lidar', choices=('lidar', 'navigation'))
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    host = HostEnvironment()
    distribution = 'humble' if os.uname().machine == 'aarch64' else 'jazzy'
    prefix = host.path('ros2_humble_root' if distribution == 'humble' else 'ros2_root')
    triplet = 'aarch64-linux-gnu' if distribution == 'humble' else 'x86_64-linux-gnu'
    plugin = prefix/'usr/lib'/triplet/'qt5/plugins'
    executable = host.executable('rviz2')
    command = [executable] if executable else ['ros2', 'run', 'rviz2', 'rviz2']
    if args.check:
        command.append('--help')
    else:
        if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
            parser.error('RViz2 requires a graphical session; --check is available without a desktop')
        name = 'rs16-readonly.rviz' if args.view == 'lidar' else 'navigation-readonly.rviz'
        command += ['-d', str(resource_root()/'configs/rviz'/name)]
    argv, env = host.ros_command(command, distribution=distribution)
    if (plugin/'platforms').is_dir():
        env.update(QT_PLUGIN_PATH=str(plugin), QT_QPA_PLATFORM_PLUGIN_PATH=str(plugin/'platforms'))
    if args.check:
        env['QT_QPA_PLATFORM'] = 'offscreen'
    os.execvpe(argv[0], argv, env)


if __name__ == '__main__':
    main()
