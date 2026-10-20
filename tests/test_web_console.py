import http.client
from contextlib import closing
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

from application.operator_service import OperatorService
from web_ui.server import ConsoleServer, load_token
from tests.test_llm_proposals import Application


class WebTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.token=load_token(Path(self.directory.name)/'token')
        self.backend=Application()
        self.service=OperatorService(self.backend,self.directory.name,missions=['basic_route'])
        self.server=ConsoleServer(('127.0.0.1',0),self.service,self.token,Path(self.directory.name)/'audit.jsonl')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.port=self.server.server_address[1]
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=2);self.directory.cleanup()
    def call(self,path,body=None,**extra):
        headers={'Authorization':'Bearer '+self.token,'Host':f'127.0.0.1:{self.port}'}
        if body is not None:
            headers.update({'Content-Type':'application/json','X-VAF-CSRF':self.token})
        headers.update(extra)
        with closing(http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)) as client:
            client.request('POST' if body is not None else 'GET',path,
                           json.dumps(body) if body is not None else None,headers)
            response=client.getresponse();data=response.read()
            return response.status,data,dict(response.getheaders())
    def test_real_http_auth_csrf_origin_host_and_validation(self):
        self.assertEqual(self.call('/api/status',Authorization='')[0],401)
        self.assertEqual(self.call('/api/status',Origin='https://evil.test')[0],403)
        self.assertEqual(self.call('/api/status',Host='evil.test')[0],403)
        self.assertEqual(self.call('/api/start',{'mission':'basic_route'},**{'X-VAF-CSRF':''})[0],403)
        self.assertEqual(self.call('/api/start',{'mission':'arm'})[0],409)
        self.assertEqual(self.backend.starts,[])
        self.assertEqual(self.call('/api/start',{'mission':'basic_route'})[0],200)
        self.assertEqual(len(self.backend.starts),1)
        code,body,headers=self.call('/api/status')
        self.assertEqual(code,200);self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(self.call('/api/start',[])[0],400)
        self.assertEqual(self.call('/api/start',{'mission':'basic_route','effect':'raw'})[0],409)
        self.assertEqual(self.call('/api/../token')[0],404)
    def test_waypoint_map_preview_and_no_user_chosen_output_paths(self):
        result=self.call('/api/waypoint',{'name':'A','x':1.,'y':2.,'frame':'map'})
        self.assertEqual(result[0],200)
        self.assertFalse(json.loads(result[1])['result']['control_eligible'])
        self.assertEqual(self.call('/api/map/load',{'sha256':'../../secret'})[0],409)
        self.assertEqual(self.call('/api/waypoint',{'name':'../x','x':1.,'y':2.,'frame':'map'})[0],409)
        self.assertEqual(self.backend.starts,[])
    def test_token_permissions_and_public_bind_refused(self):
        path=Path(self.directory.name)/'weak';path.write_text('a'*64);path.chmod(0o644)
        with self.assertRaises(ValueError):load_token(path)
        with self.assertRaises(ValueError):ConsoleServer(('0.0.0.0',0),self.service,self.token,Path(self.directory.name)/'public.log')
    def test_model_offline_does_not_mutate_vehicle(self):
        self.assertEqual(self.call('/api/propose',{'text':'route'})[0],409)
        self.assertEqual(self.call('/api/status')[0],200)
        self.assertEqual(self.backend.starts,[])
    def test_blocked_remote_llm_cannot_block_cancel_use_case(self):
        from intelligence.proposals import MissionProposal
        entered,release=threading.Event(),threading.Event()
        class Model:
            def propose(self,*args):
                entered.set();release.wait(timeout=3)
                return MissionProposal('clarify',None,'test')
        class Backend:
            def handle(self,operation,payload):
                return {'cancelled':True} if operation=='cancel' else {'profile':'rover_sim'}
        service=OperatorService(Backend(),self.directory.name,llm=Model(),missions=['basic_route'])
        worker=threading.Thread(target=lambda:service.handle('propose',{'text':'wait'}));worker.start()
        try:
            self.assertTrue(entered.wait(timeout=1))
            finished=threading.Event()
            cancel=threading.Thread(target=lambda:(service.handle('cancel',{}),finished.set()));cancel.start()
            self.assertTrue(finished.wait(timeout=.5),'LLM held cancel lock')
            cancel.join(timeout=1)
        finally:
            release.set();worker.join(timeout=2)
