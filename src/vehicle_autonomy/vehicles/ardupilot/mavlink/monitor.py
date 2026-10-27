"""Untrusted telemetry framing for display; never authenticates control state."""
from pymavlink.dialects.v20 import ardupilotmega as mav


class MonitorFramer:
    def __init__(self):
        self.parser=mav.MAVLink(None)
        self.parser.robust_parsing=True

    def feed(self,data):
        # A read is bounded by the byte transport. Never mirror a credential
        # provisioning payload, even if one unexpectedly appears on downlink.
        return tuple(bytes(m.get_msgbuf()) for m in (self.parser.parse_buffer(data) or [])[:128]
                     if m.get_type() not in ('BAD_DATA','SETUP_SIGNING'))
