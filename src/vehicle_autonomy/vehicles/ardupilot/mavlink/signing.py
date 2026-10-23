"""Opt-in receive authentication for one explicitly provisioned MAVLink stream.

This is an ordering proof, not a request UUID or a vehicle capture clock. The
owner must retain this object across reconnects of the SAME key epoch. A fresh
object requires a newly provisioned key/initial floor, never a recycled key
with a reset replay window. There is no discovery or key setup on a vehicle.
"""
import hashlib
import hmac


class ReceiveSigning:
    def __init__(self, key: bytes, *, initial_timestamp: int, link_id: int = 0):
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError('MAVLink receive signing needs a 32-byte epoch key')
        if (type(initial_timestamp) is not int or type(link_id) is not int
                or not 0 <= initial_timestamp < 2**48 or not 0 <= link_id <= 255):
            raise ValueError('invalid signing timestamp or link ID')
        self._key = key
        self.link_id = link_id
        self.watermark = initial_timestamp
        self.rejected = dict(unsigned=0, signature=0, replay=0, stream=0)
        self.accepted = 0

    def verify(self, message, *, system: int, component: int) -> int | None:
        raw = bytes(message.get_msgbuf())
        if len(raw) < 25 or raw[0] != 0xFD or not raw[2] & 1:
            return self._reject(message, 'unsigned')
        # Authenticate BEFORE updating any watermark. Some pymavlink versions
        # update stream_timestamps before checking the MAC; don't use that path.
        if not hmac.compare_digest(hashlib.sha256(self._key + raw[:-6]).digest()[:6], raw[-6:]):
            return self._reject(message, 'signature')
        if (message.get_srcSystem(), message.get_srcComponent(), raw[-13]) != (system, component, self.link_id):
            return self._reject(message, 'stream')
        timestamp = int.from_bytes(raw[-12:-6], 'little')
        if timestamp <= self.watermark:
            return self._reject(message, 'replay')
        self.watermark = timestamp
        self.accepted += 1
        return timestamp

    def _reject(self, message, reason):
        self.rejected[reason] += 1
        message._vaf_signature_rejection = reason
        return None
