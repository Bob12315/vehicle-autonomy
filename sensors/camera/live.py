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
                      'capture_time': 'unknown; acquisition completion diagnostic',
                      'frame': 'camera_optical', 'spatial_calibration': 'unverified',
                      'exposure': 'unknown', 'error': None}
            atomic(directory / 'latest.jpg', encoded.tobytes())
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
    def __init__(self, config):
        self.directory = tempfile.TemporaryDirectory(prefix='vaf-camera-')
        self.path = Path(self.directory.name)
        self.process = subprocess.Popen([sys.executable, '-m', 'sensors.camera.live',
            '--config-json', json.dumps(config), '--output', str(self.path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def health(self):
        try:
            health = json.loads((self.path / 'health.json').read_text())
        except FileNotFoundError:
            health = {'error': 'awaiting first camera frame'}
        age = None if 'received_ns' not in health else time.monotonic_ns() - health['received_ns']
        health.update(age_ns=age, online=(not health.get('error') and self.process.poll() is None
                                        and age is not None and 0 <= age <= 1_000_000_000))
        return health

    def frame(self):
        if not self.health()['online']:
            raise ValueError('fresh camera frame unavailable')
        data = (self.path / 'latest.jpg').read_bytes()
        if len(data) > 1_000_000:
            raise ValueError('camera frame too large')
        return {'mime': 'image/jpeg', 'base64': base64.b64encode(data).decode()}

    def close(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=2)
        self.directory.cleanup()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config-json', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    return capture(json.loads(args.config_json), args.output)


if __name__ == '__main__':
    raise SystemExit(main())
