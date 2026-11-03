"""One atomic bounded preview packet; no frame/metadata pairing race."""
import json
import struct

MAX_JPEG = 1_000_000
MAX_PACKET = MAX_JPEG + 16_388
STALE_NS = 1_000_000_000


def encode(metadata, jpeg):
    header = json.dumps(metadata, allow_nan=False, separators=(',', ':')).encode()
    if len(header) > 16_384 or not 4 <= len(jpeg) <= MAX_JPEG or not jpeg.startswith(b'\xff\xd8'):
        raise ValueError('bounded JPEG and metadata required')
    return struct.pack('!I', len(header)) + header + jpeg


def decode(data):
    if not 8 <= len(data) <= MAX_PACKET:
        raise ValueError('invalid camera packet size')
    length = struct.unpack('!I', data[:4])[0]
    if not 2 <= length <= 16_384 or length + 4 >= len(data):
        raise ValueError('invalid camera metadata size')
    metadata, jpeg = json.loads(data[4:4+length]), data[4+length:]
    if type(metadata) is not dict or any(type(metadata.get(k)) is not int or metadata[k] < 0 for k in ('sequence','received_ns')):
        raise ValueError('camera sequence and host receive time required')
    if not jpeg.startswith(b'\xff\xd8') or len(jpeg) > MAX_JPEG:
        raise ValueError('invalid preview JPEG')
    return metadata, jpeg
