"""Bounded same-host SDK cloud exchange; never launders timestamps on polling."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import stat


def load_exchange(path, now_ns):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 8_000_000:
            raise ValueError('bounded regular LiDAR exchange required')
        payload = stream.read(8_000_001)
    if len(payload) > 8_000_000:
        raise ValueError('LiDAR exchange too large')
    value = json.loads(payload)
    required = {'schema','source','epoch','clock_domain','frame','sequence','capture_ns',
                'receive_ns','source_timestamp_s','provenance','points'}
    if type(value) is not dict or set(value) != required or value['schema'] != 1 or value['source'] != 'robosense.rs_driver':
        raise ValueError('official rs_driver cloud envelope required')
    if (type(value['epoch']) is not str or not 1 <= len(value['epoch']) <= 128
            or value['provenance'] not in ('pcap_replay','live_sdk_system_timestamp')
            or type(value['source_timestamp_s']) not in (int,float) or not math.isfinite(value['source_timestamp_s'])):
        raise ValueError('explicit SDK provenance, timestamp and epoch required')
    if value['clock_domain'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
        raise ValueError('LiDAR exchange belongs to a different host boot')
    if (any(type(value[key]) is not int for key in ('sequence','capture_ns','receive_ns'))
            or not value['epoch'] or value['frame'] != 'lidar' or value['sequence'] < 0
            or not 0 <= value['capture_ns'] <= value['receive_ns'] <= now_ns
            or now_ns - value['capture_ns'] > 500_000_000):
        raise ValueError('LiDAR frame/time/epoch unavailable or stale')
    points = value['points']
    if type(points) is not list or not 1 <= len(points) <= 200_000:
        raise ValueError('LiDAR cloud missing or point budget exceeded')
    if any(type(p) is not list or len(p) != 3 or
           any(type(v) not in (int,float) or not math.isfinite(v) for v in p) for p in points):
        raise ValueError('invalid LiDAR point')
    return value


def read_exchange(path, now_ns):
    value = load_exchange(path, now_ns)
    return exchange_view(value, now_ns)


def exchange_view(value, now_ns):
    points = value['points']
    return {'online': True, 'source': value['source'], 'epoch': value['epoch'],
            'frame': value['frame'], 'sequence': value['sequence'], 'points': len(points),
            'capture_ns': value['capture_ns'], 'age_ns': now_ns-value['capture_ns'],
            'preview_xyz': points[::max(1,len(points)//1000)][:1000],
            'provenance': value['provenance'], 'control_eligible': False,
            'reason': 'mount/exposure clock, ground/body filters and physical acceptance unqualified'}


class ExchangeMonitor:
    def __init__(self):
        self.previous = None
        self.dropped = 0

    def poll(self, path, now_ns):
        value = load_exchange(path, now_ns)
        key = value['epoch'], value['sequence'], value['capture_ns']
        if self.previous is not None:
            epoch, sequence, capture = self.previous
            if key[0] != epoch:
                raise ValueError('SDK source epoch changed; restart read-only admission')
            if key[1] < sequence or key[2] < capture or (key[1] == sequence and key[2] != capture):
                raise ValueError('SDK sequence/timestamp regression or version reuse')
            if key[1] > sequence:
                if key[2] <= capture:
                    raise ValueError('new SDK sequence reused capture timestamp')
                self.dropped += key[1] - sequence - 1
        self.previous = key
        return {**exchange_view(value, now_ns), 'dropped_clouds': self.dropped}
