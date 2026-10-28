from copy import deepcopy
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
from threading import Thread
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from vehicle_autonomy.app.tools.agent import Agent
from vehicle_autonomy.app.tools.broker import AgentRegistry, AgentServer
from vehicle_autonomy.app.tools.local import LocalTools
from vehicle_autonomy.app.tools.schema import context, manifest
from vehicle_autonomy.app.tools.storage import Store
from .helpers import CTX, tool, wait


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name)/'agent'); self.addCleanup(self.store.close)

    def local(self, *items, **kw):
        local = LocalTools(items or [tool()], self.store, **kw); self.addCleanup(local.close); return local

    def test_schema_rejects_unknown_commands_paths_and_control_context(self):
        for change in ({'shell':True}, {'permissions':['vehicle_command']}, {'stop_strategy':'pid'}):
            with self.assertRaises(ValueError): manifest(tool() | change)
        for change in ({'ros_namespace':'/../bad'}, {'ros_domain_id':True}, {'vehicle_id':'../bad'}, {'environment':'hardware_controlled'}, {'command':'evil'}):
            with self.assertRaises(ValueError): context(CTX | change)

    def test_actual_process_lifecycle_and_duplicate_launch(self):
        local = self.local(); first = local.execute('launch','fixture','default',CTX)
        wait(lambda: local.snapshot()[0]['instance']['ready'])
        second = local.execute('launch','fixture','default',CTX)
        self.assertEqual(first['instance_id'],second['instance_id'])
        self.assertEqual(local.snapshot()[0]['instance']['service_health'],'HEALTHY')
        with self.assertRaises(ValueError): local.execute('launch','fixture','default',CTX | {'vehicle_id':'other'})
        local.execute('stop','fixture','default',CTX)
        wait(lambda: local.snapshot()[0]['instance']['state']=='STOPPED')
        self.assertTrue(local.snapshot()[0]['instance']['cleanup_confirmed'])
        self.assertTrue(any(e['operation']=='tool.exit' for e in self.store.events))

    def test_abnormal_exit_restart_and_no_ready_from_process_alone(self):
        local = self.local(tool(ready=False))
        local.execute('launch','fixture','default',CTX)
        wait(lambda: local.snapshot()[0]['instance']['process_running'])
        view = local.snapshot()[0]['instance']; self.assertFalse(view['ready']); self.assertEqual(view['connection'],'UNKNOWN')
        os.kill(view['pid'],signal.SIGKILL)
        wait(lambda: local.snapshot()[0]['instance']['state']=='FAILED')
        local.execute('restart','fixture','default',CTX)
        wait(lambda: local.snapshot()[0]['instance']['process_running'])
        self.assertNotEqual(view['instance_id'],local.snapshot()[0]['instance']['instance_id'])

    def test_missing_software_gui_and_external_ownership(self):
        item=tool(); item['profiles']['default']['argv'][0]='vaf-never-installed'
        local=self.local(item)
        self.assertFalse(local.snapshot()[0]['checks']['default']['installed'])
        with self.assertRaisesRegex(ValueError,'Missing Dependency'):local.execute('launch','fixture','default',CTX)
        gui=tool('gui');gui['permissions']=['desktop'];local2=self.local(gui,environment={'PATH':os.defpath})
        self.assertFalse(local2.check('gui','default')['launchable'])
        with self.assertRaisesRegex(ValueError,'Desktop Agent'):local2.execute('launch','gui','default',CTX)
        # /bin/sleep has a distinct executable, unlike the test runner's Python.
        external=subprocess.Popen(['/bin/sleep','60']);self.addCleanup(lambda:external.poll() is None and external.terminate());self.addCleanup(lambda:None)
        try:
            item=tool('sleep');item['profiles']['default']['argv']=['/bin/sleep','60']
            third=self.local(item)
            self.assertIn(external.pid,third.discover('sleep'))
            with self.assertRaisesRegex(ValueError,'external'):third.execute('launch','sleep','default',CTX)
            third.execute('stop','sleep','default',CTX);self.assertIsNone(external.poll())
        finally:external.terminate();external.wait()

    def test_timeout_cleans_descendants(self):
        item=tool(code='import subprocess,time; p=subprocess.Popen(["/bin/sleep","120"]); print(p.pid,flush=True); time.sleep(120)')
        item['profiles']['default']['ready']['contains']=['absent'];item['profiles']['default']['startup_timeout_s']=.3
        local=self.local(item);local.execute('launch','fixture','default',CTX)
        view=wait(lambda:(lambda v:v if v and v['logs'] else None)(local.snapshot()[0]['instance']))
        child=int(''.join(view['logs']).strip())
        wait(lambda:local.snapshot()[0]['instance']['state']=='FAILED')
        self.assertFalse(Path(f'/proc/{child}').exists());self.assertIn('timeout',local.snapshot()[0]['instance']['error'])

    def test_state_lock_and_private_output(self):
        with self.assertRaises(ValueError):Store(self.store.root)
        self.store.save('workspaces.json',{'x':1});self.assertEqual(self.store.load('workspaces.json',{}),{'x':1})
        self.assertEqual((self.store.root/'workspaces.json').stat().st_mode & 0o777,0o600)
        item=tool();item['profiles']['default']['env']['SECRET']='not-public'
        local=self.local(item);self.assertNotIn('not-public',json.dumps(local.snapshot()))

    def test_agent_sigkill_closes_supervisor_pipe_and_cleans_tool(self):
        destination=Path(self.tmp.name)/'pid.json'
        script='''
import json,sys,time
from pathlib import Path
from vehicle_autonomy.app.tools.local import LocalTools
from vehicle_autonomy.app.tools.storage import Store
from tests.tool_agent.helpers import tool,CTX,wait
store=Store(Path(sys.argv[1])/'crash-agent')
local=LocalTools([tool()],store)
local.execute('launch','fixture','default',CTX)
view=wait(lambda:(lambda v:v if v and v['pid'] else None)(local.snapshot()[0]['instance']))
Path(sys.argv[1],'pid.json').write_text(json.dumps({'pid':view['pid']}))
time.sleep(120)
'''
        parent=subprocess.Popen([sys.executable,'-c',script,self.tmp.name])
        try:
            wait(destination.exists);pid=json.loads(destination.read_text())['pid']
            parent.kill();parent.wait(3)
            wait(lambda:not Path(f'/proc/{pid}').exists())
        finally:
            if parent.poll() is None:parent.kill();parent.wait()


class LinkTests(unittest.TestCase):
    setUp=CoreTests.setUp
    local=CoreTests.local
    def link(self):
        store=Store(Path(self.tmp.name)/'backend');self.addCleanup(store.close)
        registry=AgentRegistry(store);token=secrets.token_urlsafe(32)
        server=AgentServer(('127.0.0.1',0),registry,{'desktop':token,'second':secrets.token_urlsafe(32)},store.root/'http.jsonl')
        thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.02});thread.start()
        def close():server.shutdown();thread.join(3);server.server_close()
        self.addCleanup(close)
        local=self.local();agent=Agent('desktop','Desktop','desktop',f'http://127.0.0.1:{server.server_address[1]}',token,local,interval_s=.1)
        agent.start();self.addCleanup(agent.close);wait(lambda:registry.snapshot()['agents'])
        return registry,agent

    def test_real_http_registration_launch_reconnect_and_auth(self):
        registry,agent=self.link()
        job=registry.submit('desktop','launch','fixture','default',CTX)
        wait(lambda:registry.jobs[job['id']]['state']=='SUCCEEDED')
        wait(lambda:registry.snapshot()['agents'][0]['tools'][0]['instance']['ready'])
        agent.exchange();self.assertEqual(len(agent.tools.instances),1)
        with self.assertRaises(HTTPError):
            urlopen(Request(agent.endpoint+'/v1/exchange',data=b'{}',headers={'Authorization':'Bearer invalid','X-VAF-Agent':'desktop','Content-Type':'application/json'}))
        registry.agents['desktop']['seen']-=10
        self.assertFalse(registry.snapshot()['agents'][0]['connected'])
        # Fresh full snapshots reconnect without starting a second process.
        wait(lambda:registry.snapshot()['agents'][0]['connected'])
        self.assertEqual(len(agent.tools.instances),1)

    def test_replayed_boot_heartbeat_and_job_timeout(self):
        registry,agent=self.link();agent.stop_event.set();agent.thread.join(3)
        saved=registry.agents['desktop'];payload={k:deepcopy(saved[k]) for k in ('boot_id','sequence','name','role','tools','results')}
        with self.assertRaisesRegex(ValueError,'replayed'):registry.exchange('desktop',payload)
        with self.assertRaisesRegex(ValueError,'active'):registry.exchange('desktop',payload | {'boot_id':'different','sequence':0})
        job=registry.submit('desktop','launch','fixture','default',CTX);registry.jobs[job['id']]['deadline']-=20
        self.assertEqual(registry.snapshot()['jobs'][-1]['state'],'EXPIRED')
        saved['seen']-=10
        with self.assertRaisesRegex(ValueError,'disconnected'):registry.submit('desktop','launch','fixture','default',CTX)


if __name__=='__main__':unittest.main()
