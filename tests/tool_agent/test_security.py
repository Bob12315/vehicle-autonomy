from copy import deepcopy
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
import secrets
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError

from vehicle_autonomy.app.tools.agent import Agent
from vehicle_autonomy.app.tools.broker import AgentRegistry,AgentServer
from vehicle_autonomy.app.tools.local import LocalTools
from vehicle_autonomy.app.tools.storage import Store
from .helpers import tool


class SecurityTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.store=Store(Path(tmp.name)/'state');self.addCleanup(self.store.close)
        self.local=LocalTools([tool()],self.store);self.addCleanup(self.local.close)
        self.registry=AgentRegistry(self.store)

    def payload(self,**kw):return dict(boot_id='boot',sequence=0,name='Desktop',role='desktop',tools=self.local.snapshot(),results=[])|kw

    def test_bad_report_is_rejected_before_advancing_identity_or_state(self):
        payload=self.payload();payload['tools'][0]['manifest']['profiles']['default']['argv']=['/bin/sh']
        with self.assertRaises(ValueError):self.registry.exchange('desktop',payload)
        self.assertFalse(self.registry.agents)
        payload=self.payload(results=[dict(id='job',ok='yes',result=None,error=None)])
        with self.assertRaises(ValueError):self.registry.exchange('desktop',payload)
        self.assertFalse(self.registry.agents)

    def test_orphaned_results_after_backend_restart_are_acknowledged_without_execution(self):
        response=self.registry.exchange('desktop',self.payload(results=[dict(id='old-job',ok=True,result={'state':'RUNNING'},error=None)]))
        self.assertEqual(response['acknowledged'],['old-job']);self.assertEqual(response['commands'],[]);self.assertFalse(self.registry.jobs)

    def test_agents_cannot_share_one_credential(self):
        token=secrets.token_urlsafe(32)
        with self.assertRaisesRegex(ValueError,'distinct'):AgentServer(('127.0.0.1',0),self.registry,{'one':token,'two':token},self.store.root/'http.jsonl')

    def test_agent_never_forwards_credentials_on_http_redirect(self):
        reached=[]
        class Target(BaseHTTPRequestHandler):
            def do_GET(self):reached.append(self.headers.get('Authorization'));self.send_response(200);self.end_headers()
            def log_message(self,*args):pass
        target=HTTPServer(('127.0.0.1',0),Target)
        class Redirect(BaseHTTPRequestHandler):
            def do_POST(self):self.send_response(302);self.send_header('Location',f'http://127.0.0.1:{target.server_address[1]}/');self.end_headers()
            def log_message(self,*args):pass
        source=HTTPServer(('127.0.0.1',0),Redirect);threads=[]
        for server in (source,target):
            t=Thread(target=server.serve_forever,kwargs={'poll_interval':.02});t.start();threads.append(t)
        try:
            agent=Agent('desktop','Desktop','desktop',f'http://127.0.0.1:{source.server_address[1]}',secrets.token_urlsafe(32),self.local)
            with self.assertRaises(HTTPError):agent.exchange()
            self.assertEqual(reached,[])
        finally:
            for server in (source,target):server.shutdown();server.server_close()
            for t in threads:t.join(3)
