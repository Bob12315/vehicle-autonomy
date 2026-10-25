"""Authenticated Action Lab API using the shared registry and scheduler."""
from datetime import datetime,timezone
from pathlib import Path
from threading import Event,Thread
from urllib.parse import urlsplit,parse_qs
import json
import re
import time

from vehicle_autonomy.actions.catalog import register_standard
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.engine.action.registry import ActionRegistry
from vehicle_autonomy.engine.action.runtime import ActionRuntime
from vehicle_autonomy.app.web.server import ConsoleServer,Handler


class ActionLab:
    def __init__(self,drivers,*,registry=None,event_sink=None):
        self.drivers=dict(drivers);self.registry=registry or ActionRegistry()
        if registry is None:register_standard(self.registry)
        self.clock=lambda:TimePoint(time.monotonic_ns(),datetime.now(timezone.utc),'host-monotonic-simulation')
        self.runtime=ActionRuntime(self.registry,self.drivers,clock=self.clock,event_sink=event_sink,max_instances=512)
        self._stop=Event();self._thread=Thread(target=self._run,name='action-lab-scheduler',daemon=True);self._thread.start()
    def _run(self):
        while not self._stop.wait(.05):self.runtime.tick()
    def handle(self,operation,payload):
        if operation=='vehicles':return [d.info() for d in self.drivers.values()]
        if operation=='catalog':
            target=payload.get('target')
            if target:
                ctx=self.drivers[target].context()
                return self.registry.catalog(vehicle_kind=ctx.target_kind,capabilities=ctx.capabilities)
            return self.registry.catalog()
        if operation=='instances':return self.runtime.views()
        if operation=='resources':return self.runtime.resource_view()
        if operation=='run':
            allowed={'name','target','parameters','version','allow_send','timeout_s','wait_timeout_s','continuation_of'}
            if payload.keys()-allowed:raise ValueError('unknown Action request fields')
            return self.runtime.submit(**payload)
        if operation=='cancel':
            if set(payload)!={'id'}:raise ValueError('cancel requires Action id only')
            return self.runtime.cancel(payload['id'])
        raise ValueError('unsupported Action operation')
    def close(self):
        # Closing the server does not claim any aircraft has stopped. Driver
        # shutdown uses the same independent Execution barriers as cancellation.
        terminal={'SUCCEEDED','FAILED','REJECTED','CANCELLED','TIMED_OUT','UNKNOWN'}
        for r in self.runtime.views():
            if r['state'] not in terminal or r['safety'] and r['safety']['continuation_allowed']:
                self.runtime.cancel(r['id'])
        until=time.monotonic()+14
        while time.monotonic()<until and any(r['state'] not in terminal for r in self.runtime.views()):time.sleep(.05)
        self._stop.set();self._thread.join(5)
        errors=[]
        for d in self.drivers.values():
            try:d.close()
            except Exception as exc:errors.append(type(exc).__name__)
        if errors:raise RuntimeError('Action driver cleanup failed: '+','.join(errors))


class ActionLabServer(ConsoleServer):
    def __init__(self,address,service,token,audit_path):
        super().__init__(address,service,token,audit_path)
        self.RequestHandlerClass=ActionLabHandler


class ActionLabHandler(Handler):
    post_routes={'/api/run':'run','/api/cancel':'cancel'}
    max_json_bytes=8192
    def do_GET(self):
        static={'/':('action-lab.html','text/html; charset=utf-8'),
            '/action-lab.js':('action-lab.js','application/javascript'),'/action-lab.css':('action-lab.css','text/css')}
        if self.path in static:
            name,kind=static[self.path];self.reply(200,(Path(__file__).parent/'static'/name).read_bytes(),kind);return
        if not self.authorized():return
        try:parts=urlsplit(self.path);query=parse_qs(parts.query,strict_parsing=True)
        except ValueError:self.reply(400,{'ok':False,'error':'invalid Action query'});return
        routes={'/api/vehicles':'vehicles','/api/actions':'catalog','/api/instances':'instances','/api/resources':'resources'}
        if parts.path not in routes or query.keys()-{'target'} or any(len(v)!=1 for v in query.values()):
            self.reply(404,{'ok':False,'error':'unknown Action route'});return
        self.invoke(routes[parts.path],{k:v[0] for k,v in query.items()})
    def do_POST(self):
        if not self.authorized(mutation=True):return
        operation=self.post_routes.get(self.path)
        try:
            if not operation or self.headers.get('Transfer-Encoding'):raise ValueError('unsupported route or encoding')
            if self.headers.get('Content-Type')!='application/json':raise ValueError('JSON required')
            length=int(self.headers.get('Content-Length','-1'))
            if not 0<=length<=self.max_json_bytes:raise ValueError('bounded JSON required')
            payload=json.loads(self.rfile.read(length),parse_constant=lambda _:(_ for _ in ()).throw(ValueError('finite JSON required')))
            if type(payload) is not dict:raise ValueError('JSON object required')
            identifier=self.headers.get('X-VAF-Request-ID','')
            if not re.fullmatch(r'[A-Za-z0-9:_-]{1,128}',identifier):raise ValueError('request ID required')
        except (ValueError,TypeError) as exc:
            self.reply(400,{'ok':False,'error':str(exc)});return
        canonical=json.dumps([operation,payload],sort_keys=True,allow_nan=False)
        with self.server.request_lock:
            if identifier in self.server.requests:
                old,code,response=self.server.requests[identifier]
                if canonical!=old:self.reply(409,{'ok':False,'error':'request ID reused with different content'})
                else:self.reply(code,response)
                return
            if len(self.server.requests)>=4096:
                self.reply(409,{'ok':False,'error':'mutation budget exhausted'});return
            code,response=self.invoke(operation,payload,mutation=True,send=False)
            self.server.requests[identifier]=canonical,code,response
            self.reply(code,response)
