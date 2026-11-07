"""ROS-free validation of actual Gazebo packed clouds; never generate ranges."""
import math
import struct


FIELDS = [('x', 0, 7), ('y', 4, 7), ('z', 8, 7), ('intensity', 12, 7),
          ('range', 16, 7), ('ring', 20, 4), ('time', 24, 7),
          ('offset_time', 28, 6), ('timestamp', 32, 8)]
POINT_STEP = 40


def convert(message):
    """Preserve finite scene returns and their snapshot acquisition time.

    `time` seconds / `offset_time` nanoseconds are deliberately zero. `timestamp`
    is absolute simulation nanoseconds (float64). Uniform raster rows are `ring`,
    not fabricated MID-360 `line` or Livox CustomMsg. Not deskew validation data.
    """
    # Protobuf bytes access creates a copy. Reading message.data per coordinate
    # copied hundreds of MB/GB per scan and made real messages stale in flight.
    raw=message.data
    if (not 0 < message.width <= 200000 or not 0 < message.height <= 256
            or message.width * message.height > 250000
            or not 12 <= message.point_step <= 256
            or message.row_step < message.width * message.point_step
            or len(raw) != message.row_step * message.height
            or len(raw) > 64_000_000):
        raise ValueError('invalid or oversized Gazebo cloud layout')
    fields = {f.name: f for f in message.field}
    if len(fields) != len(message.field):
        raise ValueError('duplicate cloud field')
    required = ['x', 'y', 'z']
    for name in required + (['intensity'] if 'intensity' in fields else []):
        field = fields.get(name)
        # gz.msgs FLOAT32=6; ROS sensor_msgs/PointField FLOAT32=7.
        if field is None or field.datatype != 6 or field.count != 1 or not 0 <= field.offset <= message.point_step-4:
            raise ValueError('unsupported Gazebo XYZ/intensity layout')
    stamp = message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nsec
    if stamp < 0 or not 0 <= message.header.stamp.nsec < 1_000_000_000:
        raise ValueError('invalid capture stamp')
    endian = '>' if message.is_bigendian else '<'
    output = bytearray()
    minimum, maximum, intensity_available = float('inf'), 0., 'intensity' in fields
    elevations = []
    for row in range(message.height):
        for col in range(message.width):
            offset = row * message.row_step + col * message.point_step
            xyz = [struct.unpack_from(endian+'f', raw, offset+fields[k].offset)[0] for k in required]
            if not all(math.isfinite(v) for v in xyz):
                continue
            distance = math.sqrt(sum(v*v for v in xyz))
            if not .099 <= distance <= 40.1:
                continue
            intensity = struct.unpack_from(endian+'f', raw, offset+fields['intensity'].offset)[0] if intensity_available else 0.
            if not math.isfinite(intensity):
                intensity = 0.
            output.extend(struct.pack('<fffffH2xfId', *xyz, intensity, distance, row, 0., 0, float(stamp)))
            minimum, maximum = min(minimum, distance), max(maximum, distance)
            elevations.append(math.degrees(math.atan2(xyz[2], math.hypot(*xyz[:2]))))
    return bytes(output), dict(stamp_ns=stamp, points=len(output)//POINT_STEP,
        source_width=message.width, source_height=message.height,
        range_min_m=None if not output else minimum, range_max_m=None if not output else maximum,
        elevation_min_deg=min(elevations) if elevations else None,
        elevation_max_deg=max(elevations) if elevations else None,
        intensity_available=intensity_available, timing='simultaneous_snapshot_zero_offsets')


def fresh(last, now, bound=1_000_000_000):
    return type(last) is int and 0 <= now-last <= bound
