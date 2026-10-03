"""Simulation payload inventory and its independent state observation producer."""
from uuid import uuid4
from contracts.core.primitives import SchemaVersion
from contracts.core.quality import QualityState
from contracts.sensor import DetectedObject,Observation

class SimPayloadPort:
    def __init__(self,inventory=('sim_payload_1',),*,reject_release=False):
        self.loaded=set(inventory);self.released={};self.commands={};self.reject_release=reject_release
        self.producer='sim.payload:'+uuid4().hex;self.sequence=0
    @property
    def state_producer_id(self):return self.producer
    def release(self,command,now):
        key=str(command.effect_id)
        if key in self.commands:
            if self.commands[key]!=command:raise ValueError('payload effect ID conflict')
            return
        effect=command.effect
        if self.reject_release:raise RuntimeError('simulated_payload_rejection')
        if effect.payload_id not in self.loaded:raise RuntimeError('payload_not_loaded')
        self.loaded.remove(effect.payload_id);self.commands[key]=command
        self.released[effect.payload_id]=(effect.target_id,effect.target_position,now,key)
    def poll(self,now):
        output=[]
        for payload,(target,position,mutated,key) in self.released.items():
            if now.elapsed_ns_since(mutated)<=0:continue
            self.sequence+=1
            output.append(Observation(f'{self.producer}:{self.sequence}',SchemaVersion(1,0),self.producer,self.sequence,now,now,
                QualityState.VALID,DetectedObject(payload+'@'+target,'sim_payload_released',position,1.0),'odom'))
        return tuple(output)
    def inventory(self):
        return {'loaded':sorted(self.loaded),'released':{p:{'target':t,'position':[v.x,v.y,v.z],'mutated_ns':at.monotonic_ns,'effect_id':key} for p,(t,v,at,key) in self.released.items()}}
