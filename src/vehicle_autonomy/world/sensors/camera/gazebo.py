"""Explicit read-only Gazebo RGB subscriber, with a single replaceable input."""
import json
from collections import deque
import signal
from threading import Event, Lock
import time

from .packet import encode


def clock_pair(sim_ns, system_ns, host_ns, wall_ns):
    age = wall_ns-system_ns
    if not -100_000_000 <= age <= 500_000_000:
        raise ValueError('Gazebo system clock publication stale')
    return sim_ns, host_ns-age


def fresh_capture(pair, captured, now):
    return bool(pair is not None and 0 <= now-pair[1] <= 750_000_000
                and -100_000_000 <= pair[0]-captured <= 750_000_000)


def capture(config, directory):
    import cv2
    import numpy as np
    from gz.transport13 import Node
    from gz.msgs10.clock_pb2 import Clock
    from gz.msgs10.image_pb2 import Image
    from gz.msgs10 import image_pb2
    from .live import atomic
    stop, lock = Event(), Lock()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    pending = None
    sequence = dropped = 0
    last_capture = None
    fault = None
    latest_clock = None
    received_times = deque(maxlen=30)

    def clock(message):
        nonlocal latest_clock
        system = message.system.sec*1_000_000_000 + message.system.nsec
        # Reject queued old clock publications using the same host's system
        # timestamp; simulated and host monotonic epochs remain distinct.
        sim = message.sim.sec*1_000_000_000 + message.sim.nsec
        try: pair = clock_pair(sim, system, time.monotonic_ns(), time.time_ns())
        except ValueError: return
        with lock: latest_clock = pair

    def ingest(message):
        nonlocal pending, dropped, fault, last_capture
        received = time.monotonic_ns()
        stamp = message.header.stamp
        captured = stamp.sec * 1_000_000_000 + stamp.nsec
        with lock:
            if last_capture is not None and captured <= last_capture:
                fault = 'Gazebo capture clock repeated or regressed'; pending = None
                return
            last_capture = captured
            if not (1 <= message.width <= 4096 and 1 <= message.height <= 2160 and len(message.data) <= 32_000_000):
                fault = 'invalid or oversized Gazebo image'; pending = None
                return
            if pending is not None: dropped += 1
            pending = (message, received, captured, time.time_ns())

    node = Node()
    clock_topic = '/world/'+config['world']+'/clock'
    if not node.subscribe(Clock, clock_topic, clock):raise RuntimeError('Gazebo clock subscription failed')
    if not node.subscribe(Image, config['topic'], ingest):
        raise RuntimeError('Gazebo image subscription failed')
    formats = {image_pb2.RGB_INT8: cv2.COLOR_RGB2BGR,
               image_pb2.BGR_INT8: None}
    try:
        while not stop.wait(1 / config['fps']):
            with lock:
                item, pending = pending, None
                error = fault
                pair = latest_clock
            if error:
                atomic(directory/'health.json', json.dumps(dict(error=error)).encode())
                continue
            if item is None: continue
            message, received, captured, received_utc = item
            now = time.monotonic_ns()
            if not fresh_capture(pair, captured, now):
                atomic(directory/'health.json', json.dumps(dict(error='Gazebo image/clock stale or unavailable')).encode())
                continue
            if message.pixel_format_type not in formats:
                atomic(directory/'health.json', json.dumps(dict(error='unsupported Gazebo pixel format')).encode())
                continue
            stride = message.step
            if stride < message.width * 3 or len(message.data) != stride * message.height:
                atomic(directory/'health.json', json.dumps(dict(error='invalid Gazebo image stride')).encode())
                continue
            image = np.frombuffer(message.data, dtype=np.uint8).reshape(message.height, stride)[:, :message.width*3].reshape(message.height, message.width, 3)
            conversion = formats[message.pixel_format_type]
            if conversion is not None: image = cv2.cvtColor(image, conversion)
            if message.width > 640:
                image = cv2.resize(image, (640, max(1, int(message.height*640/message.width))))
            ok, jpeg = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok: continue
            sequence += 1
            received_times.append(received)
            fps = (len(received_times)-1)*1e9/max(1,received_times[-1]-received_times[0])
            metadata = dict(kind='gazebo', source=config['topic'], sequence=sequence, frames=sequence,
                width=image.shape[1], height=image.shape[0], source_width=message.width, source_height=message.height,
                fps=fps, configured_fps=config['fps'], dropped=dropped,
                received_utc_ns=received_utc, captured_ns=captured, capture_clock='gazebo-simulation', received_ns=received,
                encoded_ns=time.monotonic_ns(), clock_sim_ns=pair[0], clock_host_ns=pair[1], capture_time='Gazebo image header; not host wall time',
                frame='camera_optical', spatial_calibration='unverified', error=None)
            atomic(directory/'latest.packet', encode(metadata, jpeg.tobytes()))
            atomic(directory/'health.json', json.dumps(metadata).encode())
    finally:
        node.unsubscribe(config['topic'])
        node.unsubscribe(clock_topic)
    return 0
