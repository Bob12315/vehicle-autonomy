"""Pure public-protocol setup for a fresh owned, unarmed local SITL epoch.

No sockets, credential files or vehicle motion. The trusted bootstrap owns
the session lifetime; ordinary receivers cannot provision/reset their epoch.
"""
from pymavlink.dialects.v20 import ardupilotmega as mav
from .signing import ReceiveSigning


class FreshSimulationSigning:
    def __init__(self,system_id,key,seed):
        self.system_id=system_id;self.key=key;self.seed=seed
        self.auth=ReceiveSigning(key,initial_timestamp=seed)
        self.peer=mav.MAVLink(None,srcSystem=250,srcComponent=191)
        self.parser=mav.MAVLink(None);self.parser.robust_parsing=True
        self.setup=self.requested=False;self.frames=[]

    def _pack(self,message):
        result=message.pack(self.peer);self.peer.seq=(self.peer.seq+1)&255
        return result

    def feed(self,data):
        replies=[]
        for message in self.parser.parse_buffer(data) or []:
            if message.get_type()=='BAD_DATA' or (message.get_srcSystem(),message.get_srcComponent())!=(self.system_id,1):continue
            if not self.setup:
                if message.get_type()!='HEARTBEAT':continue
                if message.base_mode&128:raise RuntimeError('signing provisioning requires unarmed owned SITL')
                replies.append(self._pack(self.peer.setup_signing_encode(self.system_id,1,self.key,self.seed)))
                self.setup=True;continue
            stamp=self.auth.verify(message,system=self.system_id,component=1)
            if stamp is None:continue
            if message.get_type() in ('HEARTBEAT','COMMAND_ACK'):
                self.frames.append(dict(type=message.get_type(),timestamp=stamp,
                    raw_hex=bytes(message.get_msgbuf()).hex(),payload=message.to_dict()))
            if message.get_type()=='HEARTBEAT' and not self.requested:
                replies.append(self._pack(self.peer.command_long_encode(self.system_id,1,512,0,0,0,0,0,0,0,0)))
                self.requested=True
        return replies

    @property
    def complete(self):
        return (any(f['type']=='HEARTBEAT' for f in self.frames) and
                any(f['type']=='COMMAND_ACK' and f['payload']['command']==512 for f in self.frames))

    def crosscheck(self):
        independent=mav.MAVLink(None)
        independent.signing.secret_key=self.key;independent.signing.timestamp=self.seed
        for item in self.frames:
            decoded=independent.parse_buffer(bytes.fromhex(item['raw_hex']))
            if not decoded or not decoded[0].get_signed():
                raise AssertionError('independent pymavlink signature verification failed')

    def parameter_requests(self,names):
        # Readback uses a new TCP stream, retaining the authenticated watermark
        # but never splicing a partial frame from the provisioning connection.
        self.parser=mav.MAVLink(None);self.parser.robust_parsing=True
        return tuple(self._pack(self.peer.param_request_read_encode(self.system_id,1,name.encode(),-1)) for name in names)

    def parameter_values(self,data):
        values={}
        for message in self.parser.parse_buffer(data) or []:
            if message.get_type()=='BAD_DATA':continue
            if self.auth.verify(message,system=self.system_id,component=1) is None:continue
            if message.get_type()=='PARAM_VALUE':values[str(message.param_id).rstrip('\0')]=float(message.param_value)
        return values
