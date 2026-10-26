"""Authenticated public TIMESYNC causality bounds, never heartbeat association.

A pose with a boot timestamp >= an authenticated response was produced after
that response's corresponding host request. Use the host SEND time as a
conservative capture LOWER bound. No rate-one assumption, extrapolation or
receipt-time refreshing. ACK and HEARTBEAT have no boot sample and stay None.
"""
from collections import deque
from dataclasses import replace
from datetime import timedelta
import secrets


class TimesyncSourceClock:
    PERIOD_NS=50_000_000
    MAX_RTT_NS=200_000_000
    def __init__(self):
        self._anchors=deque(maxlen=64);self._pending=None;self._last_request=None;self._nonce=secrets.randbits(61)+1;self.last_boot={}
        self.accepted=0;self.rejected=0;self.last_rtt_ns=None
    def request_due(self,now):
        if self._pending is not None:
            nonce,sent,marker=self._pending
            if now.elapsed_ns_since(sent)<self.MAX_RTT_NS:return None
            self._pending=None;self.rejected+=1
        if self._last_request is not None and now.elapsed_ns_since(self._last_request)<self.PERIOD_NS:return None
        self._nonce+=1
        if self._nonce>=2**63:raise ValueError('clock correlation epoch exhausted')
        return self._nonce
    def sent(self,nonce,at,marker):
        self._pending=(nonce,at,marker);self._last_request=at
    def observe(self,message,received,outbound_bytes):
        if message.get_type()!='TIMESYNC' or getattr(message,'_vaf_signature_timestamp',None) is None:return False
        if self._pending is None or int(message.ts1)!=self._pending[0]:self.rejected+=1;return False
        _,sent,marker=self._pending;rtt=received.elapsed_ns_since(sent)
        self._pending=None
        boot=int(message.tc1)
        if not 0<=rtt<=self.MAX_RTT_NS or boot<=0 or self._anchors and (boot<=self._anchors[-1][0] or sent<=self._anchors[-1][1]):
            self.rejected+=1;return False
        if type(outbound_bytes) is not int or outbound_bytes<marker:self.rejected+=1;return False
        # Pinned SITL UART receive_time_constraint_us subtracts serial wire
        # time for nbytes+available(). The verified SERIAL0 baud is >=57600.
        # FIFO input means available cannot exceed bytes this sole writer sent
        # AFTER the query. Shift SOURCE threshold forward by an upper bound;
        # never pretend the corrected tc1 itself was generated after our send.
        wire_ns=(1_000_000*10//57600)*(64+outbound_bytes-marker)*1000
        threshold=boot+wire_ns
        self._anchors.append((threshold,sent));self.last_rtt_ns=rtt;self.accepted+=1;return True
    def capture(self,message,received):
        kind=message.get_type()
        if kind in ('HEARTBEAT','COMMAND_ACK'):return None
        if kind not in ('LOCAL_POSITION_NED','GLOBAL_POSITION_INT','ATTITUDE','GPS_RAW_INT'):return received
        if kind=='GPS_RAW_INT':
            micros=int(message.time_usec)
            if not 0<micros<1_000_000_000_000:return None
            boot=micros*1000
        else:boot=int(message.time_boot_ms)*1_000_000
        if kind in self.last_boot and boot<self.last_boot[kind]:raise ValueError('AP source boot regressed; new timing/session epoch required')
        self.last_boot[kind]=boot
        candidates=[host for source,host in self._anchors if source<=boot]
        if not candidates:return None
        bound=candidates[-1]
        if bound.clock_domain_id!=received.clock_domain_id or bound>received:raise ValueError('source clock correlation mismatch')
        return replace(received,monotonic_ns=bound.monotonic_ns,utc=received.utc-timedelta(microseconds=received.elapsed_ns_since(bound)//1000))
