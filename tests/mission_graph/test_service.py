from dataclasses import replace
from datetime import datetime,timezone
import json
from pathlib import Path
import secrets
import tempfile
from threading import Thread
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from uuid import uuid4

from tests.action_system.test_runtime import Driver,Factory,Parameters
from vehicle_autonomy.app.web.mission_control import MissionControl,MissionControlServer
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.core.primitives import SchemaVersion,ResourceVersion
from vehicle_autonomy.contracts.world.models import WorldSnapshot
from vehicle_autonomy.contracts.decision import ActionSpec
from vehicle_autonomy.engine.action.registry import ActionRegistry
from tests.mission_graph.test_graph import graph,leaf


class WebDriver(Driver):
    session='simulation:one'
    def info(self):return dict(target='v',kind='rover',connected=True,session_id=self.session,system_send=False,action_send=False)
    def snapshot(self):return WorldSnapshot(SchemaVersion(1,0),'test',ResourceVersion("test",1),TimePoint(time.monotonic_ns(),datetime.now(timezone.utc),'host-monotonic-simulation'))
    def close(self):pass


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.driver=WebDriver();self.registry=ActionRegistry();self.registry.register_typed(ActionSpec('ok',Parameters,external_lifecycle='typed_only'),Factory())
        binding=patch('vehicle_autonomy.app.web.mission_control.bind_simulations',return_value={})
        binding.start();self.addCleanup(binding.stop)
        self.lab=MissionControl({'v':self.driver},Path(self.tmp.name),registry=self.registry)
        self.addCleanup(self.lab.close);self.token=secrets.token_urlsafe(32)
        self.server=MissionControlServer(('127.0.0.1',0),self.lab,self.token,Path(self.tmp.name)/'http.jsonl')
        self.thread=Thread(target=self.server.serve_forever,kwargs={'poll_interval':.02});self.thread.start()
        self.addCleanup(self.close_server);self.base='http://127.0.0.1:'+str(self.server.server_address[1])
    def close_server(self):self.server.shutdown();self.thread.join(3);self.server.server_close()
    def api(self,path,payload=None,identifier=None,csrf=True,auth=True):
        headers={'Authorization':'Bearer '+self.token} if auth else {}
        if payload is not None:
            headers.update({'Content-Type':'application/json','X-VAF-Request-ID':identifier or uuid4().hex})
            if csrf:headers['X-VAF-CSRF']=self.token
        req=Request(self.base+path,data=None if payload is None else json.dumps(payload).encode(),headers=headers)
        try:
            with urlopen(req,timeout=3) as response:return response.status,json.load(response)
        except HTTPError as e:return e.code,json.load(e)
    def test_static_pages_and_original_action_lab_preserved(self):
        for path in ('/','/studio','/control','/console','/tool-console.js','/tool-console.css','/mission-api.js','/mission-studio.js','/manual-control.js','/mission-ui.css'):
            with urlopen(self.base+path) as r:self.assertEqual(r.status,200)
        self.assertEqual(self.api('/api/studio/state')[1]['result']['vehicles'][0]['target'],'v')
        self.assertEqual(self.api('/api/actions')[0],200)
        for path in ('/control','/console'):
            with urlopen(Request(self.base+path,headers={'Authorization':'Bearer '+self.token})) as response:html=response.read().decode()
            self.assertIn('data-navigation',html)
            self.assertIn('/navigation.js',html)
        navigation=self.api('/api/ui/navigation')[1]['result']
        self.assertIn(dict(id='studio',href='/studio',label='任务编排',description='任务编辑与运行'),navigation['items'])

    def test_console_uses_existing_state_and_preserves_auth_and_no_writes(self):
        self.assertEqual(self.api('/api/console/state',auth=False)[0],401)
        code,result=self.api('/api/console/state')
        self.assertEqual(code,200);self.assertEqual(result['result']['vehicles'][0]['id'],'v')
        self.assertIsNone(result['result']['vehicles'][0]['position'])
        self.assertIsNone(result['result']['tools']);self.assertEqual(self.driver.writes,[])
    def test_readonly_vehicle_stream_endpoint_preserves_auth_and_no_effects(self):
        code,data=self.api('/api/world/vehicle?target=v')
        self.assertEqual(code,200);self.assertEqual(data['result']['target'],'v')
        self.assertIn('world',data['result']);self.assertFalse(data['result']['system_send'])
        self.assertEqual(self.api('/api/world/vehicle?target=v',auth=False)[0],401)
        self.assertEqual(self.api('/api/world/vehicle')[0],400)
        self.assertEqual(self.api('/api/world/vehicle?target=v&extra=1')[0],400)
        code,projected=self.api('/api/world/vehicle?target=v&projection=ap')
        self.assertEqual(code,200)
        self.assertEqual(self.api('/api/world/vehicle?target=v&projection=unknown')[0],400)
        self.assertEqual(self.driver.writes,[]);self.assertEqual(self.lab.runtime.views(),[])

    def test_readonly_vehicle_cut_is_not_blocked_by_mission_journal_lock(self):
        from threading import Event,Thread
        done=Event();received=[]
        def read():
            received.append(self.api('/api/world/vehicle?target=v'));done.set()
        with self.lab._control_lock:
            thread=Thread(target=read);thread.start()
            self.assertTrue(done.wait(1),'read-only AP feed waited on Mission arbitration/journal')
        thread.join(2);self.assertFalse(thread.is_alive());self.assertEqual(received[0][0],200)
        self.assertEqual(self.driver.writes,[])

    def test_save_validate_start_do_not_collide_on_shared_request_id(self):
        payload={'spec':graph(leaf())};request_id=uuid4().hex
        self.assertEqual(self.api('/api/missions/validate',payload,request_id)[0],200)
        # Route is part of the canonical mutation, so cannot silently reuse an unrelated response.
        self.assertEqual(self.api('/api/missions/save',payload,request_id)[0],409)
        self.assertEqual(self.api('/api/missions/save',payload)[0],200)
        code,data=self.api('/api/missions/start',payload);self.assertEqual(code,200)
        identifier=data['result']['id'];deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            v=self.lab.missions.view(identifier)
            if v['state']=='SUCCEEDED':break
            time.sleep(.05)
        self.assertEqual(v['state'],'SUCCEEDED');self.assertEqual(self.driver.writes,[])
    def test_duplicate_start_same_id_returns_single_instance(self):
        p={'spec':graph(leaf())};request_id=uuid4().hex
        code,a=self.api('/api/missions/start',p,request_id);code2,b=self.api('/api/missions/start',p,request_id)
        self.assertEqual((code,code2),(200,200));self.assertEqual(a,b);self.assertEqual(len(self.lab.missions.views()),1)
    def test_auth_csrf_and_unknown_parameters_fail(self):
        self.assertEqual(self.api('/api/studio/state',auth=False)[0],401)
        self.assertEqual(self.api('/api/missions/start',{'spec':graph(leaf())},csrf=False)[0],403)
        self.assertEqual(self.api('/api/missions/start',{'spec':graph(leaf()),'force':True})[0],409)
        self.assertEqual(self.lab.runtime.views(),[])
    def test_mission_blocks_original_action_lab_bypass(self):
        d=graph(dict(id='wait',type='Wait',duration_s=10))
        code,result=self.api('/api/missions/start',{'spec':d});self.assertEqual(code,200)
        code,_=self.api('/api/run',{'name':'ok','target':'v','parameters':{}})
        self.assertEqual(code,409);self.assertEqual(self.lab.runtime.views(),[])
        self.api('/api/missions/cancel',{'id':result['result']['id']});time.sleep(.15)
        self.assertEqual(self.api('/api/run',{'name':'ok','target':'v','parameters':{}})[0],200)
    def test_takeover_requests_exit_without_implicit_authorization(self):
        self.api('/api/missions/start',{'spec':graph(dict(id='wait',type='Wait',duration_s=10))})
        code,result=self.api('/api/control/takeover',{'target':'v'})
        self.assertEqual(code,200);self.assertFalse(result['result']['authorization_granted']);self.assertEqual(self.driver.writes,[])
    def test_invalid_mission_not_saved(self):
        d=graph(leaf());d['nodes'][0]['parameters']={'count':False}
        self.assertEqual(self.api('/api/missions/save',{'spec':d})[0],409)
        self.assertEqual(self.lab.journal.data['versions'],{})

if __name__=='__main__':unittest.main()
