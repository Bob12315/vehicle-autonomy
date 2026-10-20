"""Receive-only Rover diagnostic composition, with no vehicle command port."""
import time
from protocols.mavlink.readonly import TelemetryDiagnostics, ReceiveDecoder


class ReadOnlyTelemetry:
    def __init__(self, config):
        from infrastructure.transports.readonly import ReadOnlySerial
        self.serial = ReadOnlySerial(config['path'], config['baudrate'])
        self.decoder = ReceiveDecoder()
        self.monitor = TelemetryDiagnostics()

    def poll(self):
        data = self.serial.read(65536)
        for message in self.decoder.parse(data):
            self.monitor.ingest(message, time.monotonic_ns())

    def close(self):
        self.serial.close()
