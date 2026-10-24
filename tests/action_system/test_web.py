"""Real loopback HTTP admission, shared registry and client-independent life."""
import json
from pathlib import Path
import secrets
import tempfile
from threading import Thread
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from vehicle_autonomy.app.web.action_lab import ActionLab,ActionLabServer
from vehicle_autonomy.contracts.action import ActionKind
from tests.action_system.test_runtime import Driver,Factory,Parameters
from vehicle_autonomy.contracts.decision import ActionSpec
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect
from vehicle_autonomy.engine.action.registry import ActionRegistry


class WebActionTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.driver=Driver();self.driver.close=lambda:None
        self.driver.info=lambda:{'target':'v','kind':'rover','connected':True,'system_send':False}
        registry=ActionRegistry();registry.register_typed(ActionSpec('demo',Parameters,kind=ActionKind.CONTINUOUS,effect_types=(ArmEffect,)),Factory(continuous=True,emit=True))
        self.lab=ActionLab({'v':self.driver},registry=registry);self.token=secrets.token_urlsafe(32)
        self.server=ActionLabServer(('127.0.0.1',0),self.lab,self.token,Path(self.directory.name)/'audit.jsonl')
        self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_address[1]}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.lab.close();self.thread.join(2);self.directory.cleanup()
    def api(self,path,payload=None,*,auth=True,csrf=True,request_id='test',extra=None):
        headers={}
        if auth:headers['Authorization']='Bearer '+self.token
        if payload is not None:
            headers.update({'Content-Type':'application/json','X-VAF-Request-ID':request_id})
            if csrf:headers['X-VAF-CSRF']=self.token
        headers.update(extra or {})
        request=Request(self.base+path,data=None if payload is None else json.dumps(payload).encode(),headers=headers)
        try:
            with urlopen(request,timeout=3) as response:return response.status,json.load(response)
        except HTTPError as exc:return exc.code,json.load(exc)
    def test_auth_csrf_origin_host_and_unknown_input_fail_closed(self):
        self.assertEqual(self.api('/api/vehicles',auth=False)[0],401)
        p={'name':'demo','target':'v'}
        self.assertEqual(self.api('/api/run',p,csrf=False)[0],403)
        self.assertEqual(self.api('/api/run',p,extra={'Origin':'http://evil.invalid'})[0],403)
        self.assertEqual(self.api('/api/vehicles',extra={'Host':'evil.invalid'})[0],403)
        self.assertEqual(self.api('/api/run',dict(p,unknown=True))[0],409)
        self.assertEqual(self.driver.writes,[])
    def test_dynamic_schema_shared_runtime_and_disconnect_does_not_cancel(self):
        _,body=self.api('/api/actions?target=v')
        self.assertEqual(body['result'][0]['parameters']['properties']['count']['maximum'],10)
        payload={'name':'demo','target':'v','parameters':{'count':2},'allow_send':True}
        _,body=self.api('/api/run',payload);identifier=body['result']['id']
        time.sleep(.25)
        # Each API call creates and closes a real HTTP connection.
        _,body=self.api('/api/instances');a=body['result'][0]
        self.assertEqual(a['state'],'RUNNING');current=self.lab.runtime.view(identifier)
        for key in ('id','state','parameters','kind','name'):self.assertEqual(a[key],current[key])
        self.assertEqual(len(self.driver.writes),1)
        _,again=self.api('/api/run',payload)
        self.assertEqual(again['result']['id'],identifier);self.assertEqual(len(self.lab.runtime.views()),1)
        self.assertEqual(self.api('/api/run',dict(payload,parameters={'count':3}))[0],409)
        self.api('/api/cancel',{'id':identifier},request_id='cancel');time.sleep(.2)
        self.assertEqual(self.lab.runtime.view(identifier)['state'],'CANCELLED')
    def test_static_form_contains_no_frontend_action_parameter_catalog(self):
        with urlopen(self.base+'/action-lab.js') as response:script=response.read().decode()
        self.assertIn('a.parameters.properties',script)
        self.assertNotIn('height_m',script);self.assertNotIn('vx_mps',script)
        self.assertNotIn(self.token,script)


if __name__=='__main__':unittest.main()
