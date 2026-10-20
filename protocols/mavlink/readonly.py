"""Receive-only protocol diagnostics: no heartbeat, stream request or parameter write."""
from __future__ import annotations

import math
import time
from uuid import uuid4


class ReceiveDecoder:
    def __init__(self):
        from pymavlink.dialects.v20 import ardupilotmega
        self.decoder = ardupilotmega.MAVLink(None)
        self.decoder.robust_parsing = True

    def parse(self, data):
        return self.decoder.parse_buffer(data) or ()


class TelemetryDiagnostics:
    def __init__(self):
        self.epoch = uuid4().hex
        self.source = None
        self.facts = {}
        self.previous_position = None
        self.last_boot_ms = {}
        self.fault = None

    def ingest(self, message, now_ns):
        kind = message.get_type()
        if kind == 'BAD_DATA':
            return
        source = (message.get_srcSystem(), message.get_srcComponent())
        if self.source is None:
            if kind != 'HEARTBEAT' or int(message.autopilot) != 3 or int(message.type) != 10:
                return
            self.source = source
        if source != self.source:
            return
        if hasattr(message, 'time_boot_ms'):
            stamp = int(message.time_boot_ms)
            previous = self.last_boot_ms.get(kind)
            if previous is not None and stamp <= previous:
                if stamp < previous:
                    self.fault = 'source_epoch_regression; reconnect and re-admit required'
                return
            self.last_boot_ms[kind] = stamp
        if kind not in ('HEARTBEAT', 'GPS_RAW_INT', 'GLOBAL_POSITION_INT', 'ATTITUDE',
                        'EKF_STATUS_REPORT', 'SYS_STATUS', 'GPS_GLOBAL_ORIGIN', 'STATUSTEXT'):
            return
        value = message.to_dict()
        if kind == 'GLOBAL_POSITION_INT':
            lat, lon = int(message.lat) / 1e7, int(message.lon) / 1e7
            if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                self.fault = 'invalid_global_position'
                return
            if self.previous_position:
                old_lat, old_lon, old_ns = self.previous_position
                distance = 6378137 * math.hypot(math.radians(lat - old_lat),
                    math.radians(lon - old_lon) * math.cos(math.radians(old_lat)))
                dt = (now_ns - old_ns) / 1e9
                if distance > 3 + max(0, dt) * 2:
                    self.fault = 'gps_jump; stationary re-admission required'
                    return
            self.previous_position = lat, lon, now_ns
            value['velocity_enu_mps'] = [message.vy / 100, message.vx / 100, -message.vz / 100]
        self.facts[kind] = value, now_ns

    def view(self, now_ns):
        facts = {key: {'value': value, 'receive_age_ns': now_ns - stamp,
                       'capture_time': 'unknown; receive time is diagnostic only'}
                 for key, (value, stamp) in self.facts.items()}
        gps = facts.get('GPS_RAW_INT')
        position = facts.get('GLOBAL_POSITION_INT')
        ekf = facts.get('EKF_STATUS_REPORT')
        hb = facts.get('HEARTBEAT')
        reasons = []
        for key, fact in (('heartbeat', hb), ('gps', gps), ('position', position), ('ekf', ekf)):
            if fact is None or not 0 <= fact['receive_age_ns'] <= 1_000_000_000:
                reasons.append(key + '_missing_or_stale')
        if gps and gps['value'].get('fix_type', 0) < 3:
            reasons.append('gps_fix_below_3d')
        if ekf:
            flags = ekf['value'].get('flags', 0)
            # attitude, horizontal velocity, absolute horizontal position;
            # constant-position mode and uninitialized EKF are never admitted.
            if flags & 19 != 19 or flags & (128 | 1024):
                reasons.append('ekf_quality_insufficient')
        if self.fault:
            reasons.append(self.fault)
        return {'epoch': self.epoch, 'source': self.source, 'facts': facts,
                'gps_diagnostic_eligible': not reasons, 'reasons': reasons,
                'control_eligible': False,
                'control_block': 'physical timing, origin, geofence and chassis acceptance incomplete'}

