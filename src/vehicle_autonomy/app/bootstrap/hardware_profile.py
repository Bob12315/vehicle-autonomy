"""Fail-closed onboard composition profiles; no control authorization fields."""
from __future__ import annotations

import json
import math
from pathlib import Path


def load_profile(path):
    value = json.loads(Path(path).read_text())
    fields = {'schema', 'mode', 'system_send', 'action_send', 'telemetry',
              'camera', 'lidar_exchange', 'period_s'}
    if type(value) is not dict or set(value) != fields or type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError('strict onboard schema 1 required')
    if value['system_send'] is not False or value['action_send'] is not False:
        raise ValueError('onboard SEND gates must both remain false')
    if value['mode'] not in ('simulation', 'hardware_readonly', 'hardware_controlled'):
        raise ValueError('unknown deployment mode')
    if value['mode'] == 'hardware_controlled':
        raise ValueError('hardware control is unimplemented; onsite independent safety acceptance required')
    period = value['period_s']
    if type(period) not in (float, int) or not math.isfinite(period) or not .05 <= period <= 1:
        raise ValueError('period outside .05..1 seconds')
    telemetry = value['telemetry']
    if telemetry is not None:
        if (type(telemetry) is not dict or set(telemetry) != {'path', 'baudrate'}
                or type(telemetry['path']) is not str or not telemetry['path'].startswith('/dev/serial/by-id/')
                or type(telemetry['baudrate']) is not int or telemetry['baudrate'] not in (57600, 115200, 921600)):
            raise ValueError('explicit stable serial-by-id path and supported baudrate required')
    camera = value['camera']
    if camera is not None:
        if type(camera) is not dict or set(camera) != {'kind', 'path', 'fps'}:
            raise ValueError('explicit camera kind/path/fps required')
        if camera['kind'] not in ('v4l2', 'recording') or type(camera['path']) is not str:
            raise ValueError('unsupported camera source')
        if camera['kind'] == 'v4l2' and not camera['path'].startswith('/dev/video'):
            raise ValueError('local V4L2 path required')
        if camera['kind'] == 'recording' and not Path(camera['path']).is_file():
            raise ValueError('recording must be a real regular file')
        if type(camera['fps']) not in (int, float) or not 1 <= camera['fps'] <= 15:
            raise ValueError('camera output rate must be 1..15 FPS')
    if value['lidar_exchange'] is not None and (
            type(value['lidar_exchange']) is not str or not Path(value['lidar_exchange']).is_absolute()):
        raise ValueError('absolute lidar exchange path required')
    return value
