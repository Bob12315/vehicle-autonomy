"""Explicit unit/browser fixtures; these are not SITL qualification."""
from contextlib import ExitStack
from datetime import datetime,timezone
import json,secrets,tempfile,time
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request,urlopen,build_opener,HTTPCookieProcessor
from http.cookiejar import CookieJar
from unittest.mock import patch
from uuid import uuid4

from tests.action_system.test_runtime import Driver,Parameters,Factory
from vehicle_autonomy.app.web.mission_control import MissionControl,MissionControlServer
from vehicle_autonomy.contracts.core.geometry import Pose3,Quaternion,Twist3,Vector3
from vehicle_autonomy.contracts.core.primitives import ResourceVersion,SchemaVersion
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.core.stamped import Stamped
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.vehicle.models import VehicleStateSnapshot,VehicleHealth,VehicleOperation
from vehicle_autonomy.contracts.world.models import WorldSnapshot
from vehicle_autonomy.contracts.decision import ActionSpec
from vehicle_autonomy.engine.action.registry import ActionRegistry

class FixtureDriver(Driver):
 def __init__(self,kind='rover'):
  super().__init__();self.kind=kind;self.session='fixture-session';self.connected=True;self.fresh=True;self.owned=True;self.send=True
 def info(self):return dict(target=self.kind,kind=self.kind,connected=self.connected,session_id=self.session,owned_simulation=self.owned,deployment_send=self.send,system_send=False,action_send=False,scope=None,lease_active=False)
 def context(self):
  from vehicle_autonomy.contracts.action import ActionContext
  from vehicle_autonomy.actions.catalog import capabilities
  return ActionContext(self.kind,self.kind,frozenset(capabilities(self.kind)),True)
 def snapshot(self):
  now=TimePoint(time.monotonic_ns(),datetime.now(timezone.utc),'host-monotonic-simulation')
  pose=Stamped('odom',now,Pose3(Vector3(0,0,0),Quaternion(0,0,0,1)));twist=Stamped('odom',now,Twist3(Vector3(0,0,0),Vector3(0,0,0)))
  state=VehicleStateSnapshot(SchemaVersion(1,0),self.kind,ResourceVersion('vehicle',1),now,VehicleHealth(QualityState.VALID if self.fresh else QualityState.INVALID),pose,twist,operation=VehicleOperation(armed=False,native_mode='ARDUPILOT_CUSTOM_0'))
  return WorldSnapshot(SchemaVersion(1,0),'fixture-world',ResourceVersion('world',1),now,vehicle=state)
 def close(self):pass

class Harness:
 def __init__(self,directory=None,*,kinds=('rover',),standard=False):
  self.stack=ExitStack()
  self.directory=Path(directory) if directory else Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
  self.directory.mkdir(parents=True,exist_ok=True)
  self.stack.enter_context(patch('vehicle_autonomy.app.web.mission_control.bind_simulations',return_value={}))
  self.drivers={k:FixtureDriver(k) for k in kinds};registry=ActionRegistry();registry.register_typed(ActionSpec('ok',Parameters),Factory())
  if standard:
   from vehicle_autonomy.actions.catalog import register_standard
   register_standard(registry)
  self.lab=MissionControl(self.drivers,self.directory/'mission',registry=registry);self.stack.callback(self.lab.close)
  self.token=secrets.token_urlsafe(32);self.server=MissionControlServer(('127.0.0.1',0),self.lab,self.token,self.directory/'http.jsonl')
  self.thread=Thread(target=self.server.serve_forever,kwargs={'poll_interval':.02});self.thread.start();self.stack.callback(self.close_server)
  self.base='http://127.0.0.1:'+str(self.server.server_address[1])
 def close_server(self):self.server.shutdown();self.thread.join(3);self.server.server_close()
 def close(self):self.stack.close()
 def client(self):return Client(self)

class Client:
 def __init__(self,h):self.h=h;self.cookies=CookieJar();self.http=build_opener(HTTPCookieProcessor(self.cookies));self.csrf='';self.control=''
 def call(self,path,payload=None,*,headers=None,identifier=None):
  hdr={}
  if payload is not None:hdr.update({'Content-Type':'application/json','Origin':self.h.base,'X-VAF-CSRF':self.csrf,'X-VAF-Request-ID':identifier or uuid4().hex})
  if self.control:hdr['X-VAF-Control']=self.control
  hdr.update(headers or {})
  try:
   with self.http.open(Request(self.h.base+path,None if payload is None else json.dumps(payload).encode(),hdr),timeout=4) as r:
    data=r.read();return r.status,json.loads(data) if r.headers.get('Content-Type')=='application/json' else data,r.headers
  except HTTPError as e:return e.code,json.load(e),e.headers
 def login(self):
  code,data,headers=self.call('/api/auth/login',{'key':self.h.token});assert code==200,(code,data)
  self.csrf=data['result']['csrf'];return headers
 def acquire(self,target='rover'):
  code,data,_=self.call('/api/control/acquire',{'target':target});assert code==200,(code,data)
  self.control=data['result']['control_token'];return data['result']
