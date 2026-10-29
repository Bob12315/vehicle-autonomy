"""Private inherited-FD proxy for the existing ActionDriver, never a new writer.

Each explicitly launched worker constructs the original signed Driver and its
Execution/Safety/Authority. UI serialization and Python GC in the application
cannot delay that owner's safety cycle. Only typed ActionDriver calls cross the
OS-owned pipe; no public listener, raw command API or signing key crosses it.
"""
from concurrent.futures import Future
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timezone
import json
from multiprocessing.connection import Pipe,Connection
from pathlib import Path
import sys
from threading import Event,RLock,Thread
import time
from types import SimpleNamespace
from uuid import uuid4

from vehicle_autonomy.contracts.action_ports import ActionAdmissionRejected
from vehicle_autonomy.contracts.core.time import TimePoint
from .faults import FaultSettings,SoftwareFaultLink


class DependencyView:
    """Read-only projection; live assertion is executed by the actual proof."""
    def __init__(self,driver,metadata):
        self.driver=driver
        for key,value in metadata.items():setattr(self,key,value)
        self.path=Path(self.path);self.root=self.path.parent
        self.receive_signing=SimpleNamespace(accepted=0,rejected={},watermark=0)

    def assert_alive(self):
        self.driver._call('assert_alive').result(timeout=3)


class ReceiveLinkView:
    def __init__(self,driver):
        self.driver=driver;self.settings=FaultSettings();self._diagnostics={}
    def configure(self,payload):
        settings=self.driver._call('fault',payload).result(timeout=3)
        self.settings=settings
    @property
    def dropped(self):return self._diagnostics.get('dropped_chunks',0)
    def diagnostics(self):return dict(self._diagnostics)
    def begin_capture(self):self.driver._call('capture',True).result(timeout=3)
    def end_capture(self):return self.driver._call('capture',False).result(timeout=3)
    def inject_received(self,data):return self.driver._call('inject_received',data).result(timeout=3)


class ProcessVehicleDriver:
    def __init__(self,target,profile,session,*,model_kind,seed,allow_send):
        self.target=target;self.profile=profile;self.allow_send=allow_send
        self._lock=RLock();self._send_lock=RLock();self._pending={};self._retiring=Event()
        self._ready=Event();self._closed=False;self._expected_close=False;self._error=None
        self._info={};self._world=None;self._context=None;self._effects={};self._feedback={};self._guards={}
        self.ownership=None;self.link=ReceiveLinkView(self)
        self.clock=lambda:TimePoint(time.monotonic_ns(),datetime.now(timezone.utc),profile.clock_domain_id)
        parent,child=Pipe(duplex=True);self.connection=parent
        config=session.directory/'framework-worker.json'
        config.write_text(json.dumps(dict(target=target,profile=str(session.directory/'profile.toml'),
            manifest=str(session.directory/'manifest.json'),kind=model_kind,seed=seed,allow_send=allow_send)))
        try:
            self.process=session.start('framework-worker',[sys.executable,'-m',__name__,str(config),str(child.fileno())],pass_fds=(child.fileno(),))
        finally:child.close()
        self.connection.send(('boot',))
        self._reader=Thread(target=self._read,name='simulation-evidence-'+target,daemon=True);self._reader.start()
        if not self._ready.wait(12):raise TimeoutError('signed Framework worker startup timed out')
        if self._error:raise RuntimeError(self._error)

    def _read(self):
        try:
            while True:
                message=self.connection.recv()
                if message[0]=='state':
                    _,info,world,context,effects,feedback,guards,proof,verification,link=message
                    with self._lock:
                        self._info,self._world,self._context=info,world,context
                        self._effects,self._feedback,self._guards=effects,feedback,guards
                        if self.ownership is None:self.ownership=DependencyView(self,proof)
                        verifier=self.ownership.receive_signing
                        verifier.accepted,verifier.watermark=verification['accepted'],verification['watermark']
                        verifier.rejected.clear();verifier.rejected.update(verification['rejected'])
                        self.link._diagnostics=link
                    self._ready.set()
                elif message[0]=='result':
                    _,identifier,success,value=message
                    with self._lock:future=self._pending.pop(identifier,None)
                    if future and not future.done():
                        if success:future.set_result(value)
                        else:future.set_exception(value)
                elif message[0]=='error':
                    self._error=message[1];self._ready.set()
        except (EOFError,OSError) as exc:
            if not self._expected_close:self._error='Framework worker link lost: '+type(exc).__name__
        finally:
            with self._lock:
                self._info=dict(self._info,connected=False,system_send=False,action_send=False,lease_active=False,
                    fault=self._info.get('fault') if self._expected_close else self._error)
                for future in self._pending.values():
                    if not future.done():future.set_exception(RuntimeError(self._error or 'Framework worker closed'))
                self._pending.clear()
            self._ready.set()

    def _call(self,method,*args,**kwargs):
        future=Future();identifier=uuid4().hex
        with self._lock:
            if self._closed or self._error or self.process.poll() is not None:
                future.set_exception(RuntimeError(self._error or 'Framework worker unavailable'));return future
            if len(self._pending)>=128:
                future.set_exception(RuntimeError('bounded Framework request queue exhausted'));return future
            self._pending[identifier]=future
        try:
            with self._send_lock:self.connection.send((identifier,method,args,kwargs))
        except (OSError,EOFError) as exc:
            with self._lock:self._pending.pop(identifier,None)
            future.set_exception(RuntimeError('Framework worker send failed: '+type(exc).__name__))
        return future

    def context(self):
        with self._lock:return self._context
    def read_view(self):
        with self._lock:return dict(self._info),self._world
    def info(self):return self.read_view()[0]
    def snapshot(self):return self.read_view()[1]
    def effect_results(self,identifier):
        with self._lock:return self._effects.get(identifier,())
    def command_feedback(self,identifier):
        with self._lock:return deepcopy(self._feedback.get(identifier,[]))
    def guard_status(self,identifier):
        with self._lock:return self._guards.get(identifier)
    def set_retiring(self,retiring=True):
        if retiring:self._retiring.set()
        else:self._retiring.clear()
        if not self._closed:self._call('set_retiring',retiring).result(timeout=3)
    def open_scope(self,identifier,**kwargs):
        if self._retiring.is_set():
            future=Future();future.set_exception(ActionAdmissionRejected('vehicle epoch retiring'));return future
        return self._call('open_scope',identifier,**kwargs)
    def emit(self,identifier,envelope,*,cleanup):return self._call('emit',identifier,envelope,cleanup=cleanup)
    def begin_exit(self,identifier):self._call('begin_exit',identifier)
    def finish_scope(self,identifier,*,succeeded):return self._call('finish_scope',identifier,succeeded=succeeded)
    def close(self):
        if self._closed:return
        self._expected_close=True
        try:
            if self.process.poll() is None:self._call('close').result(timeout=20)
            self.process.wait(timeout=5)
            if self.process.returncode:raise RuntimeError('Framework worker cleanup exit '+str(self.process.returncode))
        finally:
            self._closed=True
            self.connection.close();self._reader.join(2)


def worker(config_path,descriptor):
    configuration=json.loads(Path(config_path).read_text())
    pipe=Connection(descriptor)
    from vehicle_autonomy.app.bootstrap.action_ownership import OwnedActionSimulation
    from vehicle_autonomy.app.bootstrap.action_driver import VehicleActionDriver
    from vehicle_autonomy.app.bootstrap.simulation_profile import SimulationProfile
    from vehicle_autonomy.vehicles.ardupilot.commands import ArduPilotCommandTranslator
    from vehicle_autonomy.vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator
    from vehicle_autonomy.vehicles.plane.ardupilot_commands import ArduPlaneCommandTranslator
    from vehicle_autonomy.vehicles.ardupilot.transports.bytes import TcpByteTransport
    driver=proof=link=None;pending={};identifiers=set();capturing=False;captured=[];captured_size=0
    def factory(host,port,*,timeout_s):
        nonlocal link
        link=SoftwareFaultLink(TcpByteTransport.connect(host,port,timeout_s=timeout_s),seed=configuration['seed'])
        read=link.read
        def tapped(max_bytes=4096):
            nonlocal captured_size
            data=read(max_bytes)
            if capturing and data and captured_size+len(data)<=65536:
                captured.append(bytes(data));captured_size+=len(data)
            return data
        link.read=tapped
        return link
    def publish():
        info,world=driver.read_view();verifier=proof.receive_signing
        metadata=dict(path=str(proof.path),identity=proof.identity,world=proof.world,model=proof.model,
            kind=proof.kind,port=proof.port,manifest=proof.manifest,processes=proof.processes)
        pipe.send(('state',info,world,driver.context(),{i:driver.effect_results(i) for i in identifiers},
            {i:driver.command_feedback(i) for i in identifiers},{i:driver.guard_status(i) for i in identifiers},
            metadata,dict(accepted=verifier.accepted,rejected=dict(verifier.rejected),watermark=verifier.watermark),link.diagnostics()))
    try:
        if pipe.recv()!=('boot',):raise ValueError('owned worker bootstrap required')
        proof=OwnedActionSimulation(configuration['manifest'])
        kind=configuration['kind'];profile=replace(SimulationProfile.load(configuration['profile']),port=proof.port,vehicle_id=configuration['target'])
        translator={'rover':ArduRoverCommandTranslator,'copter':ArduPilotCommandTranslator,'plane':ArduPlaneCommandTranslator}[kind](mode_ids=profile.mode_ids)
        driver=VehicleActionDriver(configuration['target'],profile,translator,proof,allow_send=configuration['allow_send'],
            transport_factory=factory,source_time_sync=True,cycle_period_ns=20_000_000)
        publish();last=time.monotonic();closing=False
        allowed={'open_scope','emit','begin_exit','finish_scope','set_retiring'}
        while not closing:
            if pipe.poll(.01):
                identifier,method,args,kwargs=pipe.recv()
                try:
                    if method=='close':
                        driver.close();publish();pipe.send(('result',identifier,True,None));closing=True;continue
                    if method=='assert_alive':proof.assert_alive();value=None
                    elif method=='fault':link.configure(*args);value=link.settings
                    elif method=='capture':
                        capturing=args[0]
                        value=b''.join(captured) if not capturing else None
                        captured=[];captured_size=0
                    elif method=='inject_received':
                        data=args[0]
                        if type(data) is not bytes or not 0<len(data)<=65536:raise ValueError('bounded captured ingress bytes required')
                        with link.lock:link.queue.appendleft((0,data))
                        value=None
                    elif method in allowed:
                        if method in {'open_scope','emit','begin_exit','finish_scope'}:identifiers.add(args[0])
                        if len(identifiers)>512:raise ValueError('bounded Action evidence budget exhausted')
                        value=getattr(driver,method)(*args,**kwargs)
                    else:raise ValueError('private ActionDriver operation not registered')
                    if isinstance(value,Future):pending[identifier]=value
                    else:publish();pipe.send(('result',identifier,True,value))
                except Exception as exc:pipe.send(('result',identifier,False,exc))
            for identifier,future in tuple(pending.items()):
                if future.done():
                    publish()
                    try:pipe.send(('result',identifier,True,future.result()))
                    except Exception as exc:pipe.send(('result',identifier,False,exc))
                    del pending[identifier]
            if time.monotonic()-last>=.1:publish();last=time.monotonic()
    except (EOFError,BrokenPipeError):pass
    except Exception as exc:
        try:pipe.send(('error',type(exc).__name__+': '+str(exc)))
        except (OSError,EOFError):pass
        raise
    finally:
        if driver:driver.close()
        elif proof:proof.close()
        pipe.close()


if __name__=='__main__':worker(sys.argv[1],int(sys.argv[2]))
