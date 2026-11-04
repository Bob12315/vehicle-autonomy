"""Owned simulation-only detachable payload port, behind PayloadExecution.

The 8/9 servo recipe maps to these two detachable bottles. This port does not
send PWM or MAVLink; there is no flight-controller output writer here.
"""
from threading import Lock
import time

from vehicle_autonomy.actions.devices.simulation_payload import SimPayloadPort
from vehicle_autonomy.engine.control.payload_execution import PayloadMutationUnconfirmed


class GazeboPayloadPort(SimPayloadPort):
    def __init__(self,entity):
        super().__init__(('payload_1','payload_2'))
        from gz.transport13 import Node
        from gz.msgs10.empty_pb2 import Empty
        from gz.msgs10.stringmsg_pb2 import StringMsg
        self.node=Node();self.empty=Empty;self.lock=Lock();self.states={};self.confirmed=set();self.publishers={};self.topics=[]
        for index in (1,2):
            payload='payload_'+str(index);topic='/'+entity+'/cuadc2026/payload/bottle'+str(index)
            self.publishers[payload]=self.node.advertise(topic+'/detach',Empty)
            def receive(message,payload=payload):
                with self.lock:self.states[payload]=(message.data,time.monotonic_ns())
            if not self.node.subscribe(StringMsg,topic+'/state',receive):raise RuntimeError('owned payload state subscription failed')
            self.topics.append(topic+'/state')
    def release(self,envelope,now):
        key=str(envelope.effect_id);payload=envelope.effect.payload_id
        if key in self.commands:
            if self.commands[key]!=envelope:raise ValueError('payload effect ID conflict')
            return
        with self.lock:state=self.states.get(payload)
        # The stock Harmonic system publishes only on transitions; a late
        # subscriber cannot infer an initial "attached" observation. Inventory
        # starts from the locked model declaration, while completion always
        # requires a new independent "detached" transition after this request.
        if state is not None and state[0]!='attached':raise ValueError('owned bottle is already detached')
        if payload not in self.loaded:raise ValueError('payload already released or unknown')
        # PayloadExecution holds the Authority lock across this synchronous
        # publication and has just rechecked SEND/Lease/TTL/session/generations.
        try:published=self.publishers[payload].publish(self.empty())
        except Exception as exc:raise PayloadMutationUnconfirmed('Gazebo detach publication uncertain') from exc
        if not published:raise PayloadMutationUnconfirmed('Gazebo detach publication unconfirmed')
        super().release(envelope,now)
    def poll(self,now):
        with self.lock:states=dict(self.states)
        for payload,(_,_,issued,_) in self.released.items():
            state=states.get(payload)
            if state and state[0]=='detached' and state[1]>issued.monotonic_ns:self.confirmed.add(payload)
            else:self.confirmed.discard(payload)
        # Do not synthesize physical success from the publish call itself.
        return tuple(o for o in super().poll(now) if str(o.data.object_id).split('@')[0] in self.confirmed)
    def close(self):
        for topic in self.topics:self.node.unsubscribe(topic)
