"""Trusted host software index; never installs software or grants vehicle authority."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import shutil
import sys

from vehicle_autonomy._resources import resource_root

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


PATH_KEYS = {'ardupilot_root', 'gazebo_plugin_root', 'fixedwing_root', 'asset_cache',
             'legacy_assets', 'ros2_root', 'ros2_setup', 'ros2_workspace',
             'ros2_humble_root', 'runtime_root', 'vision_assets',
             'slam_boundary_library', 'native_source_receiver', 'vision_python', 'rescue_model'}
EXECUTABLES = {'gazebo': 'gz', 'rviz2': 'rviz2', 'qgroundcontrol': 'QGroundControl'}
VARIABLES = {'ardupilot_root': 'VAF_ARDUPILOT_ROOT', 'gazebo_plugin_root': 'VAF_GAZEBO_PLUGIN_ROOT',
             'fixedwing_root': 'VAF_FIXEDWING_ROOT', 'asset_cache': 'VAF_SIM_ASSET_CACHE',
             'legacy_assets': 'VAF_SIM_LEGACY_ASSETS', 'ros2_root': 'VAF_ROS2_ROOT',
             'ros2_humble_root': 'VAF_ROS2_HUMBLE_ROOT', 'runtime_root': 'VAF_RUNTIME_ROOT',
             'slam_boundary_library': 'VAF_SLAM_BOUNDARY_LIBRARY'}


def _absolute(value, label):
    value = os.path.expandvars(value)
    path = Path(value).expanduser()
    if not path.is_absolute() or '$' in value or '\x00' in value or '\n' in value:
        raise ValueError(label + ' must be an absolute host path')
    return path.resolve()


class HostEnvironment:
    def __init__(self, root=None, *, config=None):
        self.root = Path(root or resource_root()).resolve()
        explicit = config or os.environ.get('VAF_ENVIRONMENT_CONFIG')
        candidates = [self.root/'environments/tools.local.toml',
                      Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home()/'.config')))/'vehicle-autonomy/tools.toml']
        self.config = Path(explicit).expanduser().resolve() if explicit else next((p for p in candidates if p.is_file()), None)
        value = tomllib.loads(self.config.read_text()) if self.config else {'schema': 1}
        if type(value.get('schema')) is not int or value['schema'] != 1 or set(value) - {'schema', 'paths', 'executables', 'environment', 'checksums', 'versions'}:
            raise ValueError('host environment schema 1 required')
        self.values = {}
        for section in ('paths', 'executables', 'environment', 'checksums', 'versions'):
            entries = value.get(section, {})
            if not isinstance(entries, dict) or any(not isinstance(v, str) or '\x00' in v or '\n' in v for v in entries.values()):
                raise ValueError('host environment ' + section + ' must contain strings')
            self.values[section] = {k: v for k, v in entries.items() if v}
        for section, keys in (('paths', PATH_KEYS), ('executables', EXECUTABLES)):
            if set(self.values[section]) - set(keys):
                raise ValueError('unknown host ' + section + ' key')
            for key, value in self.values[section].items():
                _absolute(value, key)
        if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) for key in self.values['environment']):
            raise ValueError('invalid host environment variable')
        for path, digest in self.values['checksums'].items():
            _absolute(path, 'checksum path')
            if not re.fullmatch('[0-9a-f]{64}', digest):
                raise ValueError('SHA256 checksum required')

    def path(self, key, explicit=None):
        if key not in PATH_KEYS:
            raise ValueError('unknown host path: ' + key)
        if explicit is not None:
            return Path(explicit).expanduser().resolve()
        value = os.environ.get(VARIABLES.get(key, '')) or self.values['paths'].get(key)
        if value:
            return _absolute(value, key)
        home = Path.home()
        data = Path(os.environ.get('XDG_DATA_HOME', str(home/'.local/share')))/'vehicle-autonomy'
        cache = Path(os.environ.get('XDG_CACHE_HOME', str(home/'.cache')))/'vehicle-autonomy'
        installed = self.root == Path(sys.prefix)/'share/vehicle-autonomy'
        runtime = Path(os.environ.get('XDG_STATE_HOME', str(home/'.local/state')))/'vehicle-autonomy' if installed else self.root/'runtime'
        defaults = {'ardupilot_root': home/'ardupilot', 'gazebo_plugin_root': home/'gz_ws/src/ardupilot_gazebo',
                    'fixedwing_root': home/'twin-fixedwing', 'asset_cache': cache/'simulation-assets',
                    'legacy_assets': data/'world-assets', 'ros2_root': data/'ros2-jazzy/root',
                    'ros2_humble_root': home/'vehicle-autonomy/ros2-humble/root', 'runtime_root': runtime,
                    'vision_assets': data/'vision-assets', 'slam_boundary_library': data/'native/libvaf_slam_boundary.so',
                    'native_source_receiver': data/'native/vaf_native_source_receiver'}
        return defaults.get(key)

    def executable(self, key, explicit=None):
        if key not in EXECUTABLES:
            raise ValueError('unknown host executable: ' + key)
        value = explicit if explicit is not None else self.values['executables'].get(key)
        if value:
            return str(_absolute(str(value), key))
        value = shutil.which(EXECUTABLES[key])
        if value or key != 'qgroundcontrol':
            return value
        for name in ('qgroundcontrol', 'QGroundControl.AppImage'):
            value = shutil.which(name)
            if value:
                return value
        for directory in ('Applications', 'Desktop', '桌面', 'Downloads', '.local/bin'):
            base = Path.home()/directory
            for candidate in sorted(base.glob('*QGroundControl*')) if base.is_dir() else ():
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate.resolve())
        return None

    def process_environment(self, base=None):
        env = dict(os.environ if base is None else base)
        env.update(self.values['environment'])
        # Existing explicit per-process environment remains authoritative.
        for key in self.values['environment']:
            if key in os.environ:
                env[key] = os.environ[key]
        directories = [str(_absolute(p, key).parent) for key in EXECUTABLES if (p := self.values['executables'].get(key))]
        if directories:
            env['PATH'] = os.pathsep.join([*directories, env.get('PATH', '')])
        return env

    def available(self, key):
        value = self.executable(key)
        return bool(value and Path(value).is_file() and os.access(value, os.X_OK))

    def verify(self, path):
        path = Path(path).resolve()
        expected_values = {digest for reference, digest in self.values['checksums'].items()
                           if _absolute(reference, 'checksum path') == path}
        if len(expected_values) > 1:
            raise ValueError('conflicting software checksums: ' + str(path))
        expected = next(iter(expected_values), None)
        if expected:
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''):
                    digest.update(block)
            if digest.hexdigest() != expected:
                raise ValueError('configured software SHA256 mismatch: ' + str(path))

    def ros_command(self, command, *, distribution='jazzy', workspace=True):
        if distribution not in ('jazzy', 'humble'):
            raise ValueError('unsupported ROS distribution')
        if distribution == 'humble' and os.uname().machine != 'aarch64':
            raise ValueError('the configured Humble environment requires ARM64')
        if distribution == 'humble':
            release = platform.freedesktop_os_release()
            if release.get('ID') != 'ubuntu' or release.get('VERSION_ID') != '22.04':
                raise ValueError('the configured Humble environment requires Ubuntu 22.04')
        env = self.process_environment()
        prefix = self.path('ros2_root' if distribution == 'jazzy' else 'ros2_humble_root')
        setup = self.path('ros2_setup') if distribution == 'jazzy' else None
        if setup is None:
            configured = VARIABLES['ros2_root' if distribution == 'jazzy' else 'ros2_humble_root'] in os.environ or ('ros2_root' if distribution == 'jazzy' else 'ros2_humble_root') in self.values['paths']
            system = Path('/opt/ros')/distribution/'setup.bash'
            setup = system if system.is_file() and not configured else prefix/'opt/ros'/distribution/'local_setup.bash'
        if not setup.is_file():
            raise ValueError('ROS environment missing; configure environments/tools.local.toml: ' + str(setup))
        if setup.name == 'local_setup.bash':
            env['COLCON_CURRENT_PREFIX'] = str(setup.parent)
            triplet = 'aarch64-linux-gnu' if distribution == 'humble' else 'x86_64-linux-gnu'
            libraries = [prefix/'usr/lib'/triplet, prefix/'usr/lib']
            if distribution == 'humble':
                libraries += [prefix/'usr/lib'/triplet/'blas', prefix/'usr/lib'/triplet/'lapack']
            env['LD_LIBRARY_PATH'] = ':'.join([*map(str, libraries), env.get('LD_LIBRARY_PATH', '')])
            env['PYTHONPATH'] = str(prefix/'usr/lib/python3/dist-packages') + ':' + env.get('PYTHONPATH', '')
        env.setdefault('ROS_AUTOMATIC_DISCOVERY_RANGE', 'LOCALHOST')
        env.setdefault('RMW_IMPLEMENTATION', 'rmw_fastrtps_cpp')
        overlay = self.path('ros2_workspace') if workspace else None
        if overlay is not None and not overlay.is_file():
            raise ValueError('configured ROS workspace setup missing: ' + str(overlay))
        # Paths and argv are positional arguments, never interpolated shell code.
        script = 'source "$1" >&2 || exit; shift; if [[ -n "$1" ]]; then source "$1" >&2 || exit; fi; shift; exec "$@"'
        return ['/bin/bash', '-c', script, 'vaf-ros', str(setup), str(overlay or ''), *map(str, command)], env

    def report(self):
        paths = {key: dict(path=str(p), exists=p.exists()) for key in sorted(PATH_KEYS) if (p := self.path(key)) is not None}
        tools = {key: dict(path=(p := self.executable(key)), installed=bool(p and Path(p).is_file() and os.access(p, os.X_OK))) for key in EXECUTABLES}
        checks = []
        for path in self.values['checksums']:
            try:
                self.verify(path)
                checks.append(dict(path=path, status='PASS'))
            except (OSError, ValueError) as exc:
                checks.append(dict(path=path, status='FAIL', error=str(exc)))
        return dict(schema=1, config=str(self.config) if self.config else None, paths=paths, tools=tools,
                    versions=self.values['versions'], checksums=checks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    sub = parser.add_subparsers(dest='operation', required=True)
    sub.add_parser('check')
    ros = sub.add_parser('ros')
    ros.add_argument('--distribution', choices=('jazzy', 'humble'), default='jazzy')
    ros.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    host = HostEnvironment(config=args.config)
    if args.operation == 'check':
        result = host.report()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(any(c['status'] != 'PASS' for c in result['checksums']))
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('ROS worker command required')
    argv, env = host.ros_command(command, distribution=args.distribution)
    os.execvpe(argv[0], argv, env)


if __name__ == '__main__':
    raise SystemExit(main())
