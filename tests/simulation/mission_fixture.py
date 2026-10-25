"""Owned signed SITL/Gazebo + HTTP Mission application, with independent truth."""
from pathlib import Path
from contextlib import ExitStack
from collections import deque
import gc
from unittest.mock import patch
import os
from threading import Thread, Event, current_thread
from urllib.request import Request, urlopen
from uuid import uuid4
import json
import secrets
import time

from vehicle_autonomy.app.bootstrap.action_ownership import OwnedActionSimulation
from vehicle_autonomy.app.bootstrap.action_driver import VehicleActionDriver
from vehicle_autonomy.app.web.mission_control import MissionControl,MissionControlServer
from vehicle_autonomy.vehicles.ardupilot.transports.bytes import TcpByteTransport
from vehicle_autonomy.vehicles.ardupilot.commands import ArduPilotCommandTranslator
from vehicle_autonomy.vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator
from vehicle_autonomy.vehicles.plane.ardupilot_commands import ArduPlaneCommandTranslator
from tests.simulation.launch import OwnedSimulation
from tests.simulation.oracle import GazeboTruthOracle
from tests.simulation.faults import TcpFaultProxy


class MissionFixture:
    def __init__(self,path,kind,*,registry=None,events=None,application_dir=None,provider_registry_root=None):
        self.path=Path(path);self.path.mkdir(parents=True,exist_ok=False);self.kind=kind
        self.owned=OwnedSimulation(self.path,kind,confirmation_signing=True,rover_native_rtl=kind=='rover')
        self.application_dir=Path(application_dir) if application_dir else self.path/'application'
        self.provider_registry_root=Path(provider_registry_root) if provider_registry_root else self.path/'provider-registry'
        self._initialize_registry=provider_registry_root is None
        self.registry=registry;self.events=events;self._registry_context=None;self._profile_context=ExitStack();self.timings={};self.slow_calls=[];self.gc_pauses=deque(maxlen=4096);self._gc_started={};self.writer=[];self.received=deque(maxlen=4096);self.trajectory=deque(maxlen=48000)
        self.lab=self.server=self.proxy=self.driver=None;self._stop=Event();self._thread=None;self.sampling_error=None
        self.logs={name:(self.path/name).open('w') for name in ('runtime.jsonl','trajectory.jsonl','application-rx.jsonl')}
    def start(self):
        def observed_gc(phase,info):
            generation=info['generation']
            if phase=='start':self._gc_started[generation]=time.monotonic_ns()
            elif generation in self._gc_started:
                self.gc_pauses.append(dict(generation=generation,started_ns=self._gc_started[generation],duration_ns=time.monotonic_ns()-self._gc_started[generation]))
        self._gc_callback=observed_gc;gc.callbacks.append(observed_gc)
        self.owned.start()
        from vehicle_autonomy.engine.action.durable import DurableRecord
        original_write=DurableRecord.write
        def measured_write(record,*args,**kwargs):
            return self.measure('durable:'+record.path.name,lambda:original_write(record,*args,**kwargs))
        self._profile_context.enter_context(patch.object(DurableRecord,'write',measured_write))
        proof=OwnedActionSimulation(self.path/'manifest.json')
        self.oracle=GazeboTruthOracle(self.owned.world,self.owned.model)
        self.proxy=TcpFaultProxy(self.owned.port,self.path/'proxy.jsonl',capture_payload=True)
        self.proxy.records=deque(maxlen=8192)
        fixture=self
        class Observed:
            def __init__(self,transport):
                from pymavlink.dialects.v20 import ardupilotmega as mav
                self.transport=transport;self.parser=mav.MAVLink(None);self.parser.robust_parsing=True
            def read(self,*a,**kw):
                raw=self.transport.read(*a,**kw)
                messages=self.parser.parse_buffer(raw) if raw else ()
                for m in messages or ():
                    if m.get_type()=='BAD_DATA':continue
                    record=dict(host_ns=time.monotonic_ns(),type=m.get_type(),payload=m.to_dict(),raw_hex=bytes(m.get_msgbuf()).hex())
                    fixture.received.append(record);fixture.write('application-rx.jsonl',record)
                return raw
            def write(self,data):fixture.writer.append(dict(host_ns=time.monotonic_ns(),raw_hex=data.hex()));self.transport.write(data)
            def close(self):self.transport.close()
        def connect(host,port,**kw):
            if (host,port)!=('127.0.0.1',self.owned.port):raise ValueError('explicit owned connection required')
            return Observed(TcpByteTransport.connect('127.0.0.1',self.proxy.port,**kw))
        translator={'rover':ArduRoverCommandTranslator,'copter':ArduPilotCommandTranslator,'plane':ArduPlaneCommandTranslator}[self.kind](mode_ids=self.owned.profile.mode_ids)
        self.driver=VehicleActionDriver(self.kind,self.owned.profile,translator,proof,allow_send=True,
            event_sink=lambda e:self.write('runtime.jsonl',e),transport_factory=connect)
        self.observe_driver_timing()
        from vehicle_autonomy.engine.action.provider_identity import ProviderRegistry
        self._registry_context=ExitStack()
        self._registry_context.enter_context(patch.object(ProviderRegistry,'_root',self.provider_registry_root))
        self._registry_context.enter_context(patch.dict(os.environ,{'VAF_TEST_PROVIDER_REGISTRY':str(self.provider_registry_root)}))
        if self._initialize_registry:ProviderRegistry.initialize()
        self._connect=connect
        self.lab=MissionControl({self.kind:self.driver},self.application_dir,registry=self.registry,
            events=self.events,event_sink=lambda e:self.write('runtime.jsonl',e))
        self._start_server()
        def sample_loop():
            while not self._stop.wait(.05):
                try:self.sample()
                except Exception as e:self.sampling_error=type(e).__name__+': '+str(e);return
        self._thread=Thread(target=sample_loop,daemon=True);self._thread.start()
        until=time.monotonic()+self.owned.profile.warmup_ns/1e9
        while time.monotonic()<until:
            self.owned.assert_alive()
            fault=self.driver.info().get('fault')
            if fault and fault.startswith('vehicle owner failed'):raise AssertionError(fault)
            time.sleep(.1)
        self.initial=self.truth()
        return self
    def measure(self,name,function):
        started=time.monotonic_ns()
        try:return function()
        finally:
            duration=time.monotonic_ns()-started
            data=self.timings.setdefault(name,dict(count=0,total_ns=0,max_ns=0))
            data['count']+=1;data['total_ns']+=duration;data['max_ns']=max(data['max_ns'],duration)
            if duration>=30_000_000 and len(self.slow_calls)<4096:
                self.slow_calls.append(dict(name=name,started_ns=started,duration_ns=duration,thread=current_thread().name))

    def observe_driver_timing(self):
        cycle=self.driver._runtime.cycle;publish=self.driver._publish
        self.driver._runtime.cycle=lambda:self.measure('owner_cycle',cycle)
        self.driver._publish=lambda:self.measure('owner_publish',publish)

    def _start_server(self):
        self.token=secrets.token_urlsafe(32)
        self.server=MissionControlServer(('127.0.0.1',0),self.lab,self.token,self.path/'http-audit.jsonl')
        self.http_thread=Thread(target=self.server.serve_forever,kwargs={'poll_interval':.05},daemon=True);self.http_thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_address[1])

    def reopen_application(self):
        self.server.shutdown();self.http_thread.join(3);self.server.server_close();self.lab.close()
        self.reconnect_proxy_error=self.proxy.error
        self.proxy.close()
        self.proxy=TcpFaultProxy(self.owned.port,self.path/'proxy-reconnect.jsonl',capture_payload=True)
        self.proxy.records=deque(maxlen=8192)
        time.sleep(.3)
        proof=OwnedActionSimulation(self.path/'manifest.json')
        translator={'rover':ArduRoverCommandTranslator,'copter':ArduPilotCommandTranslator,'plane':ArduPlaneCommandTranslator}[self.kind](mode_ids=self.owned.profile.mode_ids)
        self.driver=VehicleActionDriver(self.kind,self.owned.profile,translator,proof,allow_send=True,
            event_sink=lambda e:self.write('runtime.jsonl',e),transport_factory=self._connect)
        self.observe_driver_timing()
        self.lab=MissionControl({self.kind:self.driver},self.application_dir,registry=self.registry,
            events=self.events,event_sink=lambda e:self.write('runtime.jsonl',e))
        self._start_server()
        until=time.monotonic()+6
        while time.monotonic()<until:
            if self.driver.info().get('session_id') and self.driver.snapshot() and self.driver.snapshot().vehicle:return
            time.sleep(.1)
        raise AssertionError('fresh read-only reconnection failed')

    def write(self,name,value):
        self.logs[name].write(json.dumps(value)+'\n');self.logs[name].flush()
    def sample(self):
        self.owned.assert_alive();truth=self.oracle.latest()
        if truth:
            if time.monotonic_ns()-truth.host_received_ns>500_000_000:raise AssertionError('independent Gazebo truth stale')
            s=self.owned.profile.safety
            if not(s.min_x_m<=truth.x_m<=s.max_x_m and s.min_y_m<=truth.y_m<=s.max_y_m and truth.z_m<=s.max_altitude_m):
                raise AssertionError('Gazebo truth outside unchanged safety envelope')
            item=dict(host_ns=time.monotonic_ns(),sim_ns=truth.simulation_ns,position=[truth.x_m,truth.y_m,truth.z_m],
                yaw=truth.yaw_rad,speed=self.oracle.recent_speed_mps())
            self.trajectory.append(item);self.write('trajectory.jsonl',item)
        return truth
    def truth(self):
        if self.sampling_error:raise AssertionError(self.sampling_error)
        truth=self.oracle.latest()
        if not truth:raise AssertionError('independent Gazebo truth unavailable')
        if time.monotonic_ns()-truth.host_received_ns>500_000_000:raise AssertionError('Gazebo truth stale')
        return truth
    def pause(self,seconds):
        until=time.monotonic()+seconds
        while time.monotonic()<until:self.truth();time.sleep(.05)
    def api(self,route,payload=None):
        headers={'Authorization':'Bearer '+self.token}
        if payload is not None:headers.update({'Content-Type':'application/json','X-VAF-CSRF':self.token,'X-VAF-Request-ID':uuid4().hex})
        req=Request(self.base+route,data=None if payload is None else json.dumps(payload).encode(),headers=headers)
        with urlopen(req,timeout=4) as response:return json.load(response)['result']
    def wait_action(self,a,*,state='SUCCEEDED',timeout=60):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            self.truth();value=self.lab.runtime.view(a['id'])
            if value['state'] in ('SUCCEEDED','FAILED','REJECTED','CANCELLED','TIMED_OUT','UNKNOWN'):
                if value['state']!=state:raise AssertionError(str(value))
                return value
            time.sleep(.05)
        raise TimeoutError('Action did not reach '+state)
    def action(self,name,parameters=None,**kw):
        return self.api('/api/manual/action',dict(name=name,target=self.kind,parameters=parameters or {},allow_send=True,**kw))
    def wait_mission(self,identifier,*,state='SUCCEEDED',timeout=600):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            self.truth();v=self.lab.missions.view(identifier)
            if v['state'] in ('SUCCEEDED','FAILED','REJECTED','CANCELLED','TIMED_OUT','UNKNOWN'):
                if v['state']!=state:raise AssertionError('Mission '+json.dumps(v))
                return v
            time.sleep(.05)
        raise TimeoutError('Mission did not reach '+state)
    def close(self):
        errors=[]
        if self.server:
            self.server.shutdown();self.http_thread.join(3);self.server.server_close()
        if self.lab:
            try:self.lab.close()
            except Exception as e:errors.append(type(e).__name__)
        elif self.driver:
            try:self.driver.close()
            except Exception as e:errors.append(type(e).__name__)
        self._stop.set()
        if self._thread:self._thread.join(3)
        if self.proxy:self.proxy.close()
        self.owned.close()
        for stream in self.logs.values():stream.close()
        if self._registry_context:self._registry_context.__exit__(None,None,None)
        self._profile_context.close()
        if getattr(self,'_gc_callback',None) in gc.callbacks:gc.callbacks.remove(self._gc_callback)
        (self.path/'timing.json').write_text(json.dumps(dict(aggregates=self.timings,slow_calls=self.slow_calls,gc_pauses=list(self.gc_pauses),observer_limits=dict(received=4096,proxy_records=8192,trajectory=48000)),indent=2)+'\n')
        if errors:raise AssertionError('application cleanup failed: '+','.join(errors))
