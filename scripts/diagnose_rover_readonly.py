"""Finite USB Rover observation. No heartbeat, request, parameter or command writes."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import time

from infrastructure.transports.readonly import ReadOnlySerial
from protocols.mavlink.readonly import ReceiveDecoder, TelemetryDiagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, help='actual /dev/serial/by-id/ device')
    parser.add_argument('--duration', type=float, default=20)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    if not args.port.startswith('/dev/serial/by-id/') or not 2 <= args.duration <= 120:
        parser.error('stable discovered device and duration 2..120 seconds required')
    decoder = ReceiveDecoder(); monitor = TelemetryDiagnostics(); counts = Counter()
    statuses = []; received = 0; start = time.monotonic()
    connection = ReadOnlySerial(args.port, 115200)
    try:
        while time.monotonic()-start < args.duration:
            data = connection.read(65536); received += len(data)
            for message in decoder.parse(data):
                counts[message.get_type()] += 1
                monitor.ingest(message, time.monotonic_ns())
                if message.get_type() == 'STATUSTEXT':
                    statuses.append(message.to_dict()); del statuses[:-50]
            time.sleep(.005)
    finally:
        connection.close()
    diagnostic = monitor.view(time.monotonic_ns())
    heartbeat = diagnostic['facts'].get('HEARTBEAT')
    connected = heartbeat is not None and heartbeat['receive_age_ns'] < 2_000_000_000
    result = {'port': args.port, 'duration_s': time.monotonic()-start,
              'bytes_received': received, 'bytes_written': 0, 'message_counts': dict(counts),
              'status_texts': statuses, 'diagnostics': diagnostic,
              'connection_passed': connected, 'physical_vehicle_acceptance': 'NOT_TESTED'}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2))
    print(json.dumps({'connection_passed': connected, 'bytes_received': received,
        'bytes_written': 0, 'message_counts': dict(counts), 'status_texts': statuses,
        'gps_reasons': diagnostic['reasons'], 'control_eligible': False}))
    return 0 if connected else 3


if __name__ == '__main__':
    raise SystemExit(main())
