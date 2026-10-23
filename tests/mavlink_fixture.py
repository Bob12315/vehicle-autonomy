"""Wire-faithful AP frames: pymavlink.pack does not advance sender.seq itself."""
from pymavlink.dialects.v20 import ardupilotmega as mav


def pack(message, sender):
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
