from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from uuid import uuid4

from vehicle_autonomy.app.tools.agent import Agent
from vehicle_autonomy.app.tools.broker import AgentServer
from vehicle_autonomy.app.tools.local import LocalTools
from vehicle_autonomy.app.tools.service import ToolService
from vehicle_autonomy.app.tools.storage import Store
from vehicle_autonomy.app.web.mission_control import MissionControl,MissionControlServer
from .helpers import CTX,tool,wait


class Harness:
    def __init__(self,directory,items=None):
        self.stack=ExitStack();self.directory=Path(directory)
        try:
            self.stack.enter_context(patch('vehicle_autonomy.app.web.mission_control.bind_simulations',return_value={}))
            self.service=ToolService(self.directory/'backend');self.stack.callback(self.service.close)
            self.agent_token=secrets.token_urlsafe(32);self.web_token=secrets.token_urlsafe(32)
            channel=AgentServer(('127.0.0.1',0),self.service.registry,{'desktop':self.agent_token,'server':secrets.token_urlsafe(32)},self.directory/'agent-http.jsonl')
            self.channel=channel
            self.start_server(channel)
            self.lab=MissionControl({},self.directory/'mission');self.lab.tool_service=self.service;self.stack.callback(self.lab.close)
            self.web=MissionControlServer(('127.0.0.1',0),self.lab,self.web_token,self.directory/'web-http.jsonl');self.start_server(self.web)
            store=Store(self.directory/'agent');self.stack.callback(store.close)
            self.local=LocalTools(items or [tool()],store)
            self.agent=Agent('desktop','Test Desktop','desktop',f'http://127.0.0.1:{channel.server_address[1]}',self.agent_token,self.local,interval_s=.1)
            self.agent.start();self.stack.callback(self.agent.close)
            self.base=f'http://127.0.0.1:{self.web.server_address[1]}'
            wait(lambda:self.service.snapshot()['agents'])
        except BaseException:self.stack.close();raise

    def start_server(self,server):
        thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.02});thread.start()
        def close():server.shutdown();thread.join(3);server.server_close()
        self.stack.callback(close)

    def api(self,path,payload=None,*,token=None,csrf=True,request_id=None):
        token=self.web_token if token is None else token
        headers={'Authorization':'Bearer '+token}
        if payload is not None:
            headers.update({'Content-Type':'application/json','X-VAF-Request-ID':request_id or uuid4().hex})
            if csrf:headers['X-VAF-CSRF']=token
        try:
            with urlopen(Request(self.base+path,None if payload is None else json.dumps(payload).encode(),headers),timeout=5) as response:return response.status,json.load(response)
        except HTTPError as exc:return exc.code,json.load(exc)

    def operation(self,op,**kw):
        return self.api('/api/tools/operation',dict(agent_id='desktop',tool_id='fixture',profile_id='default',operation=op,context=CTX,**kw))

    def close(self):self.stack.close()


class ServiceTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.h=Harness(temporary.name);self.addCleanup(self.h.close)

    def test_backend_agent_and_web_real_lifecycle_and_idempotency(self):
        payload=dict(agent_id='desktop',tool_id='fixture',profile_id='default',operation='launch',context=CTX)
        request_id=uuid4().hex
        code,body=self.h.api('/api/tools/operation',payload,request_id=request_id);self.assertEqual(code,200)
        self.assertEqual(self.h.api('/api/tools/operation',payload,request_id=request_id)[1],body)
        job=body['result']['id'];wait(lambda:self.h.service.registry.jobs[job]['state']=='SUCCEEDED')
        wait(lambda:self.h.service.snapshot()['agents'][0]['tools'][0]['instance']['ready'])
        code,state=self.h.api('/api/console/state');self.assertEqual(code,200)
        self.assertEqual(state['result']['vehicles'],[]);self.assertTrue(state['result']['tools']['agents'][0]['tools'][0]['instance']['owned'])
        self.assertEqual(self.h.operation('stop')[0],200)
        wait(lambda:self.h.local.instances['fixture']['state']=='STOPPED')
        self.assertEqual(self.h.lab.runtime.views(),[])

    def test_auth_csrf_unknown_fields_and_unknown_profile(self):
        self.assertEqual(self.h.api('/api/console/state',token=self.h.agent_token)[0],401)
        payload=dict(agent_id='desktop',tool_id='fixture',profile_id='default',operation='launch',context=CTX)
        self.assertEqual(self.h.api('/api/tools/operation',payload,csrf=False)[0],403)
        self.assertEqual(self.h.api('/api/tools/operation',payload|{'argv':['/bin/sh']})[0],409)
        self.assertEqual(self.h.api('/api/tools/operation',payload|{'profile_id':'../secret'})[0],409)
        self.assertEqual(self.h.api('/api/tools/operation',payload|{'tool_id':'unknown'})[0],409)
        self.assertFalse(self.h.local.instances)

    def test_configuration_persistence_cannot_change_active_instance(self):
        self.h.operation('launch');wait(lambda:self.h.local.instances.get('fixture',{}).get('ready'))
        original=self.h.local.instances['fixture']['context'].copy()
        changed=CTX|{'vehicle_id':'other','ros_namespace':'/other'}
        self.assertEqual(self.h.api('/api/settings/context',changed)[0],200)
        self.assertEqual(self.h.api('/api/tools/configure',dict(agent_id='desktop',tool_id='fixture',profile_id='default',context=changed))[0],200)
        self.assertEqual(self.h.local.instances['fixture']['context'],original)
        saved=self.h.service.store.load('settings.json',{});self.assertEqual(saved['context'],changed)
        self.assertEqual(self.h.operation('check')[0],200)

    def test_multiple_agents_have_separate_credentials_and_state(self):
        store=Store(self.h.directory/'second-agent');self.addCleanup(store.close)
        local=LocalTools([tool('second-tool')],store)
        agent=Agent('server','Test Server','server',self.h.agent.endpoint,self.h.channel.credentials['server'],local,interval_s=.1)
        agent.start();self.addCleanup(agent.close)
        wait(lambda:len(self.h.service.snapshot()['agents'])==2)
        job=self.h.service.registry.submit('server','launch','second-tool','default',CTX)
        wait(lambda:self.h.service.registry.jobs[job['id']]['state']=='SUCCEEDED')
        self.assertIn('second-tool',local.instances);self.assertFalse(self.h.local.instances)


if __name__=='__main__':unittest.main()
