"""Receive-only QGC telemetry mirror on the existing transport.

No GCS socket is read and no GCS packet can reach the delegate's writer.
The wrapper never originates MAVLink messages; Execution retains its sole
writer. Mirroring is bounded and best-effort, independent of control success.
"""
import socket


class TelemetryMirror:
    def __init__(self, delegate, port, *, frames):
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('loopback monitor UDP port required')
        if not callable(frames):
            raise TypeError('explicit protocol framer required')
        self.delegate = delegate
        self.frames = frames
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM | socket.SOCK_NONBLOCK)
        self.destination = ('127.0.0.1', port)
        self.dropped = 0

    def read(self, max_bytes=4096):
        data = self.delegate.read(max_bytes)
        if data:
            try:
                for frame in self.frames(data):
                    try:
                        self.socket.sendto(frame, self.destination)
                    except OSError:
                        self.dropped += 1
            except Exception:
                self.dropped += 1
        return data

    def write(self, data):
        # Called only by the existing ArduPilotCommandPort; never by UDP input.
        self.delegate.write(data)

    def close(self):
        try:
            self.delegate.close()
        finally:
            self.socket.close()
