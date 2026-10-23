"""Wire-faithful AP frames: pymavlink.pack does not advance sender.seq itself."""
from pymavlink.dialects.v20 import ardupilotmega as mav
from vehicle_autonomy.vehicles.ardupilot.mavlink.signing import ReceiveSigning

# Public deterministic test-only key. Never loaded by application defaults.
TEST_KEY = bytes(range(32))


def receive_signing():
    return ReceiveSigning(TEST_KEY, initial_timestamp=0)


def pack(message, sender):
    if sender.signing.secret_key is None:
        sender.signing.secret_key = TEST_KEY
        sender.signing.sign_outgoing = True
        sender.signing.timestamp = 1
    data = message.pack(sender)
    sender.seq = (sender.seq + 1) & 255
    return data


def heartbeat_evidence(sender, vehicle_type, mode, armed, boot):
    """Two distinct AP heartbeats bracketed by source-timed attitude samples.

    This does not change any expected command outcome, timeout, or write count.
    The review regression separately tests one/unqualified/replayed heartbeat.
    """
    return b''.join((
        pack(sender.attitude_encode(boot,0,0,0,0,0,0),sender),
        pack(sender.heartbeat_encode(vehicle_type,3,128 if armed else 0,mode,4),sender),
        pack(sender.attitude_encode(boot+1,0,0,0,0,0,0),sender),
        pack(sender.heartbeat_encode(vehicle_type,3,128 if armed else 0,mode,4),sender),
        pack(sender.attitude_encode(boot+2,0,0,0,0,0,0),sender)))
