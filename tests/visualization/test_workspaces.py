"""Actual OS process fixtures, explicitly NOT native RViz/SITL evidence."""
from copy import deepcopy
from pathlib import Path
import sys,tempfile,unittest

from tests.tool_agent.helpers import CTX,tool,wait
from tests.tool_agent.test_service import Harness
from tests.tool_agent.test_workspaces import component,spec
from tests.web_ui.helpers import FixtureDriver


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.flag=self.root/'data-ready';self.flag.touch()
        tools=[]
        for name in ('visualization-bridge','rviz2'):
            t=tool(name);t['integrations']=['ros2.visualization'];base=t['profiles']['default'];base['env']['DISPLAY']='explicit-process-fixture'
            base['startup_timeout_s']=10;base['ready']=dict(argv=[sys.executable,'-c','from pathlib import Path;print("ready" if Path('+repr(str(self.flag))+').exists() else "waiting")'],contains=['ready'])
            t['profiles']={kind:deepcopy(base) for kind in ('rover','copter','plane')};tools.append(t)
        self.h=Harness(self.root/'service',tools,drivers={'rover':FixtureDriver('rover'),'copter':FixtureDriver('copter')});self.addCleanup(self.h.close)
    def api(self,path,payload):
        code,value=self.h.api(path,payload);self.assertEqual(code,200,value);return value['result']
    def open(self,target='rover'):return self.api('/api/visualization/open',dict(target=target))
    def ready(self,run):return wait(lambda:self.h.service.workspaces.data['runs'][run['run_id']]['state']=='READY',15)
    def test_data_loss_degrades_without_killing_process_and_recovers_when_data_returns(self):
        r=self.open();self.ready(r);pids={k:i['pid'] for k,i in self.h.local.instances.items()}
        self.flag.unlink();wait(lambda:self.h.service.workspaces.data['runs'][r['run_id']]['state']=='DEGRADED',12)
        self.assertTrue(all(i['process_running'] for i in self.h.local.instances.values()))
        self.flag.touch();self.ready(r);self.assertEqual(pids,{k:i['pid'] for k,i in self.h.local.instances.items()})
        self.assertFalse(self.h.lab.runtime.views())
    def test_repeat_open_reuses_instance_and_switch_only_releases_its_own_visualization(self):
        r=self.open();self.ready(r);same=self.open();self.assertTrue(same['reused']);self.assertEqual(same['run_id'],r['run_id'])
        pids=[i['pid'] for i in self.h.local.instances.values()];switch=self.open('copter');self.assertEqual(switch['state'],'SWITCHING')
        wait(lambda:self.h.service.workspaces.data['runs'][r['run_id']]['state']=='STOPPED',12)
        next_run=self.open('copter');self.ready(next_run);self.assertEqual(next_run['context']['ros_namespace'],'/copter')
        self.assertTrue(all(not Path('/proc',str(pid)).exists() for pid in pids));self.assertEqual(self.h.local.counter,4)
        self.assertFalse(self.h.lab.runtime.views())
    def test_shared_rviz_is_not_implicitly_killed_on_context_change(self):
        r=self.open();self.ready(r)
        other=spec('another-visual-workspace',ctx=r['context'],components=[component('visualization-bridge',profile_id='rover'),component('rviz2',['visualization-bridge'],profile_id='rover')])
        self.api('/api/workspaces/save',dict(spec=other));run=self.api('/api/workspaces/launch',dict(id=other['id']));wait(lambda:self.h.service.workspaces.data['runs'][run['id']]['state']=='READY',10)
        code,_=self.h.api('/api/visualization/open',dict(target='copter'));self.assertEqual(code,409)
        self.assertTrue(all(i['process_running'] for i in self.h.local.instances.values()));self.assertFalse(self.h.lab.runtime.views())
    def test_agent_offline_recovery_requires_explicit_instance_reconciliation(self):
        r=self.open();self.ready(r);pids={k:i['pid'] for k,i in self.h.local.instances.items()};original=self.h.agent.exchange
        def disconnected():raise OSError('explicit network process fixture')
        self.h.service.registry.timeout=.25;self.h.agent.exchange=disconnected
        run=self.h.service.workspaces.data['runs'][r['run_id']]
        wait(lambda:run['state']=='UNKNOWN' and run['recovering'],5)
        self.assertTrue(all(i['process_running'] for i in self.h.local.instances.values()))
        self.h.agent.exchange=original;self.h.service.registry.timeout=5
        wait(lambda:self.h.service.registry.snapshot()['agents'][0]['connected'],5)
        self.assertEqual(run['state'],'UNKNOWN')
        instances={c['id']:self.h.local.instances[c['tool_id']]['instance_id'] for c in run['components']}
        self.api('/api/workspaces/reconcile',dict(run_id=run['id'],decision='resume',instances=instances));self.ready(r)
        self.assertEqual(pids,{k:i['pid'] for k,i in self.h.local.instances.items()});self.assertFalse(self.h.lab.runtime.views())
