"""Explicit camera/recording worker with bounded latest-frame storage."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from .packet import encode, decode, MAX_PACKET, STALE_NS


def discover():
    """Inventory only: a device node is not evidence of a working camera."""
    result = []
    for node in sorted(Path('/sys/class/video4linux').glob('video*')):
        result.append({'path': '/dev/' + node.name,
                       'name': (node / 'name').read_text().strip(),
                       'capture_verified': False})
    return result


def atomic(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(data)
    os.replace(temporary, path)


def capture(config, directory):
    import cv2
    stop = False

    def finish(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, finish)
    source = config['path']
    camera = cv2.VideoCapture(source, cv2.CAP_V4L2 if config['kind'] == 'v4l2' else cv2.CAP_ANY)
    started, frames, dropped = time.monotonic(), 0, 0
    try:
        if not camera.isOpened():
            raise RuntimeError('camera capture source cannot be opened')
        while not stop:
            tick = time.monotonic()
            ok, image = camera.read()
            received_ns = time.monotonic_ns()
            if not ok:
                raise RuntimeError('camera disconnected, read failed or recording EOS')
            if image is None or image.size == 0:
                dropped += 1
                continue
            # Bound operator preview; perception may subscribe to the original source separately.
            height, width = image.shape[:2]
            if width > 640:
                image = cv2.resize(image, (640, max(1, int(height * 640 / width))))
            ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok or len(encoded) > 1_000_000:
                dropped += 1
                continue
            frames += 1
            elapsed = time.monotonic() - started
            health = {'kind': config['kind'], 'source': source, 'frames': frames, 'dropped': dropped,
                      'sensor_drop_count': None, 'drop_metric_scope': 'preview processing only; device drop counter unavailable',
                      'fps': frames / max(elapsed, .001), 'received_ns': received_ns,
                      'sequence': frames, 'received_utc_ns': time.time_ns(), 'width': image.shape[1], 'height': image.shape[0],
                      'configured_fps': config['fps'], 'captured_ns': None, 'capture_clock': 'unknown',
                      'encoded_ns': time.monotonic_ns(),
                      'capture_time': 'unknown; acquisition completion diagnostic',
                      'frame': 'camera_optical', 'spatial_calibration': 'unverified',
                      'exposure': 'unknown', 'error': None}
            atomic(directory / 'latest.packet', encode(health, encoded.tobytes()))
            atomic(directory / 'health.json', json.dumps(health).encode())
            delay = 1 / config['fps'] - (time.monotonic() - tick)
            if delay > 0:
                time.sleep(delay)
            else:
                dropped += max(0, int(-delay * config['fps']))
    except Exception as exc:
        atomic(directory / 'health.json', json.dumps({'kind': config['kind'], 'source': source,
            'frames': frames, 'dropped': dropped, 'error': f'{type(exc).__name__}: {exc}'}).encode())
        return 1
    finally:
        camera.release()
    return 0


class CameraSource:
    def __init__(self, config, *, owner=None, name='camera', environment=None):
        if config.get('kind') not in ('gazebo', 'v4l2', 'recording') or type(config.get('fps')) not in (int, float) or not 1 <= config['fps'] <= 15:
            raise ValueError('explicit supported camera source and 1..15 FPS required')
        if config['kind'] == 'gazebo' and (not config.get('topic', '').startswith('/') or not config.get('world')):
            raise ValueError('explicit Gazebo topic required')
        self.directory = None if owner else tempfile.TemporaryDirectory(prefix='vaf-camera-')
        self.path = Path(owner.directory)/name if owner else Path(self.directory.name)
        self.path.mkdir(mode=0o700, exist_ok=True)
        command = [sys.executable, '-m', 'vehicle_autonomy.world.sensors.camera.live',
            '--config-json', json.dumps(config), '--output', str(self.path)]
        self.process = owner.start(name, command, transient=True) if owner else subprocess.Popen(command,
            env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def health(self):
        try:
            health = json.loads((self.path / 'health.json').read_text())
        except (OSError, ValueError):
            health = {'error': 'awaiting first camera frame'}
        if type(health) is not dict:health={'error':'invalid camera health packet'}
        received=health.get('received_ns')
        age = None if type(received) is not int else time.monotonic_ns() - received
        alive = self.process.poll() is None
        online = bool(not health.get('error') and alive and age is not None and 0 <= age <= STALE_NS)
        reason = health.get('error') or (None if online else 'camera worker exited' if not alive else 'camera data stale')
        return dict(health, age_ns=age, online=online, reason=reason, worker_pid=self.process.pid,
                    state='ONLINE' if online else 'FAULT' if not alive else 'STALE')

    def packet(self):
        if not self.health()['online']:
            raise ValueError('fresh camera frame unavailable')
        with (self.path/'latest.packet').open('rb') as stream:
            metadata, jpeg = decode(stream.read(MAX_PACKET+1))
        if not 0 <= time.monotonic_ns()-metadata['received_ns'] <= STALE_NS or self.process.poll() is not None:
            raise ValueError('camera packet stale or worker stopped')
        return metadata, jpeg

    def frame(self):
        _, jpeg = self.packet()
        return {'mime': 'image/jpeg', 'base64': base64.b64encode(jpeg).decode()}

    def close(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=2)
        if self.directory:self.directory.cleanup()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config-json', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config_json)
    try:
        if config['kind'] == 'gazebo':
            from .gazebo import capture as gazebo_capture
            return gazebo_capture(config, args.output)
        return capture(config, args.output)
    except Exception as exc:
        atomic(args.output/'health.json',json.dumps(dict(kind=config['kind'],error=type(exc).__name__+': '+str(exc)[:300])).encode())
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
