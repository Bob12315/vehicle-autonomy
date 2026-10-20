"""Onboard diagnostics lifecycle. Deliberately constructs no command port."""
from __future__ import annotations

from collections import deque
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import time
from uuid import uuid4

from sensors.camera.live import CameraSource, discover


class HardwareReadOnlyRuntime:
    def __init__(self, profile, log_dir):
        if profile['mode'] != 'hardware_readonly' or profile['system_send'] or profile['action_send']:
            raise ValueError('hardware diagnostic composition only')
        self.profile = profile
        self.epoch = uuid4().hex
        self.stopping = False
        self.revision = 0
        self.started_ns = time.monotonic_ns()
        self.events = deque(maxlen=200)
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.logger = logging.getLogger('vaf.hardware.' + self.epoch)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.handler = RotatingFileHandler(log_dir / 'application.jsonl', maxBytes=2_000_000, backupCount=3)
        self.logger.addHandler(self.handler)
        self.camera = None
        self.telemetry = None
        self.errors = {}
        self.inventory = discover()
        from sensors.lidar.exchange import ExchangeMonitor
        self.lidar_monitor = ExchangeMonitor()
        self.lidar = {'online': False, 'reason': 'no admitted lidar exchange configured', 'control_eligible': False}
        self._event('started', mode='hardware_readonly', send=False)
        if profile['camera']:
            self.camera = CameraSource(profile['camera'])
        if profile['telemetry']:
            try:
                from vehicles.rover.readonly import ReadOnlyTelemetry
                self.telemetry = ReadOnlyTelemetry(profile['telemetry'])
            except Exception as exc:
                self.errors['telemetry'] = f'{type(exc).__name__}: {exc}'
                self._event('telemetry_unavailable', error=self.errors['telemetry'])

    def _event(self, event, **fields):
        value = {'event': event, 'monotonic_ns': time.monotonic_ns(), 'epoch': self.epoch, **fields}
        self.events.append(value)
        self.logger.info(json.dumps(value))

    def cycle(self):
        self.revision += 1
        if self.telemetry:
            try:
                self.telemetry.poll()
            except Exception as exc:
                self.errors['telemetry'] = f'{type(exc).__name__}: {exc}'
                self.telemetry.close()
                self.telemetry = None
                self._event('telemetry_lost', error=self.errors['telemetry'])
        if self.profile['lidar_exchange']:
            try:
                self.lidar = self.lidar_monitor.poll(self.profile['lidar_exchange'], time.monotonic_ns())
                self.errors.pop('lidar', None)
            except (ValueError, OSError) as exc:
                self.lidar = {'online': False, 'control_eligible': False, 'reason': str(exc)}
                self.errors['lidar'] = str(exc)

    def get_status(self, *, include_task=True):
        now = time.monotonic_ns()
        telemetry = None if self.telemetry is None else self.telemetry.monitor.view(now)
        hb = {} if telemetry is None else telemetry['facts'].get('HEARTBEAT', {}).get('value', {})
        return {'profile': 'onboard_readonly', 'mode': 'hardware_readonly', 'state': 'READ_ONLY',
                'session_id': self.epoch, 'world_version': {'generation': self.epoch, 'revision': self.revision},
                'connected': bool(hb and telemetry['facts']['HEARTBEAT']['receive_age_ns'] < 1_000_000_000),
                'uptime_s': (now - self.started_ns) / 1e9, 'system_send': False, 'action_send': False,
                'vehicle': None if not hb else {'armed': bool(hb['base_mode'] & 128), 'mode': hb['custom_mode']},
                'telemetry': telemetry, 'camera': None if self.camera is None else self.camera.health(),
                'camera_inventory': self.inventory, 'lidar': self.lidar,
                'localization': {'gps': {'control_eligible': False, 'reason': 'hardware timing/origin/geofence unqualified'},
                    'lidar_map': {'control_eligible': False, 'reason': 'no independently qualified SLAM localization'}},
                'mapping': {'adopted': False, 'reason': 'no qualified hardware map/TF calibration'},
                'missions': [], 'task': None, 'environment': None, 'errors': dict(self.errors),
                'physical_stop': 'UNCONFIRMED', 'logs': list(self.events),
                'hardware_acceptance': 'BLOCKED; onsite physical estop, installation and calibration required'}

    def start_mission(self, name):
        self._event('mission_rejected', mission=name)
        raise ValueError('hardware read-only composition cannot start missions or authorize motion')

    def cancel_mission(self):
        self._event('software_stop_requested', physical_stop='UNCONFIRMED')
        return {'requested': True, 'physical_stop': 'UNCONFIRMED',
                'reason': 'receive-only composition has no command writer; use physical estop'}

    def request_shutdown(self):
        self.stopping = True
        return {'stopping': True, 'physical_stop': 'UNCONFIRMED'}

    def camera_frame(self):
        if self.camera is None:
            raise ValueError('camera source is not configured')
        return self.camera.frame()

    def close(self):
        if self.camera:
            self.camera.close()
            self.camera = None
        if self.telemetry:
            self.telemetry.close()
            self.telemetry = None
        self._event('closed', physical_stop='UNCONFIRMED')
        self.logger.removeHandler(self.handler)
        self.handler.close()
