"""Explicit receive-only official SDK process configuration."""
import ipaddress
import json
import os
from pathlib import Path
import sys
from uuid import uuid4


def sensor_commands(path, profile, root, *, ros=False):
    value = json.loads(Path(path).read_text())
    if type(value) is not dict or set(value) != {'schema', 'host_ip', 'msop_port', 'difop_port', 'binary', 'exchange', 'duration_s'}:
        raise ValueError('strict RS16 receiver configuration required')
    if type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('RS16 schema 1 required')
    if type(value['host_ip']) is not str or ipaddress.ip_address(value['host_ip']).version != 4:
        raise ValueError('explicit observed IPv4 receiver required')
    for key in ('msop_port', 'difop_port'):
        if type(value[key]) is not int or not 1024 <= value[key] <= 65535:
            raise ValueError('explicit UDP ports required')
    if value['msop_port'] == value['difop_port']:
        raise ValueError('MSOP/DIFOP must use distinct ports')
    if type(value['duration_s']) is not int or not 1 <= value['duration_s'] <= 86400:
        raise ValueError('finite SDK duration required')
    binary = Path(value['binary'])
    if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError('explicit installed SDK binary required')
    exchange = Path(value['exchange'])
    if not exchange.is_absolute() or str(exchange) != profile['lidar_exchange']:
        raise ValueError('SDK output must match Application lidar exchange')
    parent = exchange.parent
    info = parent.stat()
    if not parent.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('SDK output directory must be private and owned')
    commands = [('rs16', [str(binary), value['host_ip'], str(value['msop_port']),
                         str(value['difop_port']), str(value['duration_s']), str(exchange), uuid4().hex])]
    if ros:
        commands.append(('ros_scan', [str(root/'scripts/with_ros2_humble.sh'), sys.executable,
            '-m', 'integrations.ros2.rs16_scan', '--config', str(root/'config/rs16-scan.json'),
            '--exchange', str(exchange), '--health-file', str(parent/'ros-scan-health.json')]))
    return commands
