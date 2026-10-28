from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from vehicle_autonomy.app.tools.workspaces import Workspaces,validate
from vehicle_autonomy.app.tools.agent import Agent
from vehicle_autonomy.app.tools.local import LocalTools
from vehicle_autonomy.app.tools.storage import Store
from .helpers import CTX,tool,wait
from .test_service import Harness


def component(name,depends=(),**kw):
    return dict(id=name,agent_id='desktop',tool_id=name,profile_id='default',depends_on=list(depends),optional=False,wait_for='ready',timeout_s=5)|kw


def spec(name='work',components=None,ctx=None):
    return dict(schema=1,id=name,name=name,context=ctx or CTX,components=components or [component('alpha'),component('beta',['alpha'])])


class WorkspaceSchemaTests(unittest.TestCase):
    def test_topology_cycles_unknown_dependencies_and_duplicate_assignment(self):
        value=spec(components=[component('beta',['alpha']),component('alpha')])
        self.assertEqual([c['id'] for c in validate(value)['components']],['alpha','beta'])
        bad=[spec(components=[component('alpha',['beta']),component('beta',['alpha'])]),
             spec(components=[component('alpha',['unknown'])]),spec(components=[component('alpha'),component('alpha')]),
             spec(components=[component('alpha'),component('alpha')|{'id':'alias'}]),spec(components=[component('alpha',timeout_s=float('nan'))]),
             spec(components=[component('alpha',optional=1)]),spec(ctx=CTX|{'environment':'hardware_controlled'})]
        for value in bad:
            with self.assertRaises(ValueError):validate(value)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.h=Harness(temporary.name,[tool('alpha',code='import time;print("alpha",flush=True);time.sleep(120)'),
            tool('beta',code='import time;print("beta",flush=True);time.sleep(120)')]);self.addCleanup(self.h.close)

    def request(self,path,payload):
        code,body=self.h.api('/api/workspaces/'+path,payload)
        self.assertEqual(code,200,body);return body['result']

    def launch(self,value=None):
        value=value or spec();self.request('save',{'spec':value});return self.request('launch',{'id':value['id']})

    def run_view(self,run):return self.h.service.workspaces.data['runs'][run['id']]

    def ready(self,run):return wait(lambda:self.run_view(run)['state']=='READY')

    def stop(self,run):
        self.request('stop',{'run_id':run['id']});wait(lambda:self.run_view(run)['state']=='STOPPED')

    def test_dependency_order_and_actual_owned_shutdown(self):
        run=self.launch();self.ready(run)
        alpha=self.h.local.instances['alpha'];beta=self.h.local.instances['beta']
        self.assertLess(alpha['started_at'],beta['started_at']);self.assertEqual(self.h.local.counter,2)
        self.assertEqual(self.h.lab.runtime.views(),[])
        self.stop(run);self.assertTrue(alpha['cleanup_confirmed']);self.assertTrue(beta['cleanup_confirmed'])
        self.assertFalse(self.h.service.workspaces.data['leases'])

    def test_shared_service_not_stopped_or_restarted_by_another_workspace(self):
        first=self.launch(spec('first',components=[component('alpha')]));self.ready(first)
        second=self.launch(spec('second',components=[component('alpha')]));self.ready(second)
        self.assertEqual(self.h.local.counter,1)
        payload=dict(agent_id='desktop',tool_id='alpha',profile_id='default',context=CTX,operation='stop')
        self.assertEqual(self.h.api('/api/tools/operation',payload)[0],409)
        self.assertEqual(self.h.api('/api/tools/operation',payload|{'operation':'restart'})[0],409)
        self.stop(first);self.assertTrue(self.h.local.instances['alpha']['process_running'])
        self.stop(second);wait(lambda:not self.h.local.instances['alpha']['process_running'])

    def test_shared_inflight_launch_is_deduplicated(self):
        first=self.launch(spec('first',components=[component('alpha')]));second=self.launch(spec('second',components=[component('alpha')]))
        self.ready(first);self.ready(second);self.assertEqual(self.h.local.counter,1)
        jobs=[j for j in self.h.service.registry.jobs.values() if j['operation']=='launch']
        self.assertEqual(len(jobs),1)

    def test_manual_baseline_service_is_preserved(self):
        payload=dict(agent_id='desktop',tool_id='alpha',profile_id='default',context=CTX,operation='launch')
        self.assertEqual(self.h.api('/api/tools/operation',payload)[0],200)
        wait(lambda:self.h.local.instances.get('alpha',{}).get('ready'))
        run=self.launch(spec(components=[component('alpha')]));self.ready(run);self.stop(run)
        self.assertTrue(self.h.local.instances['alpha']['process_running']);self.assertEqual(self.h.local.counter,1)
        self.assertEqual(self.h.api('/api/tools/operation',payload|{'operation':'stop'})[0],200)

    def test_all_required_dependencies_preflight_before_any_launch(self):
        run=self.launch(spec(components=[component('alpha'),component('not-installed',['alpha'])]))
        self.assertEqual(run['state'],'FAILED');time.sleep(.2);self.assertFalse(self.h.local.instances)
        self.assertFalse(self.h.service.registry.jobs)

    def test_optional_failure_is_degraded_and_retry_does_not_duplicate_core(self):
        run=self.launch(spec(components=[component('alpha'),component('missing',optional=True)]))
        wait(lambda:self.run_view(run)['state']=='DEGRADED');self.assertEqual(self.h.local.counter,1)
        self.request('retry',{'run_id':run['id']});wait(lambda:self.run_view(run)['state']=='DEGRADED')
        self.assertEqual(self.h.local.counter,1);self.stop(run)

    def test_running_threshold_is_not_misreported_as_functional_ready(self):
        self.h.local.registry['alpha']['profiles']['default']['ready']=None
        self.h.agent.exchange()
        run=self.launch(spec(components=[component('alpha',wait_for='running')]))
        wait(lambda:self.run_view(run)['state']=='PREPARED')
        self.assertFalse(self.run_view(run)['components'][0]['observed_ready']);self.stop(run)

    def test_timeout_does_not_launch_dependent_and_stop_cancels(self):
        self.h.local.registry['alpha']['profiles']['default']['ready']['contains']=['never-ready']
        self.h.local.registry['alpha']['profiles']['default']['startup_timeout_s']=20
        run=self.launch(spec(components=[component('alpha',timeout_s=1),component('beta',['alpha'])]))
        wait(lambda:self.run_view(run)['state']=='FAILED')
        self.assertNotIn('beta',self.h.local.instances);self.stop(run)

    def test_incompatible_vehicle_context_cannot_share_or_reconfigure(self):
        first=self.launch(spec('first',components=[component('alpha')]));self.ready(first)
        second=self.launch(spec('second',components=[component('alpha')],ctx=CTX|{'vehicle_id':'other'}))
        self.assertEqual(second['state'],'FAILED');self.assertEqual(self.h.local.counter,1)
        payload=dict(agent_id='desktop',tool_id='alpha',profile_id='default',context=CTX|{'vehicle_id':'other'},operation='launch')
        self.assertEqual(self.h.api('/api/tools/operation',payload)[0],409)

    def test_backend_restart_requires_explicit_pinned_instance_reconciliation(self):
        run=self.launch(spec(components=[component('alpha')]));self.ready(run)
        service=self.h.service;manager=service.workspaces;manager.close()
        with service.lock:service.workspaces=Workspaces(service)
        current=self.run_view(run);self.assertEqual(current['state'],'UNKNOWN');self.assertTrue(current['recovering'])
        self.assertEqual(self.h.local.counter,1)
        self.assertEqual(self.h.api('/api/workspaces/stop',{'run_id':run['id']})[0],409)
        self.assertEqual(self.h.api('/api/workspaces/reconcile',dict(run_id=run['id'],decision='resume',instances={'alpha':'wrong'}))[0],409)
        instance=self.h.local.instances['alpha']['instance_id']
        self.request('reconcile',dict(run_id=run['id'],decision='resume',instances={'alpha':instance}));self.ready(run);self.stop(run)

    def test_backend_restart_release_never_claims_cleanup_or_stops_service(self):
        run=self.launch(spec(components=[component('alpha')]));self.ready(run)
        service=self.h.service;service.workspaces.close()
        with service.lock:service.workspaces=Workspaces(service)
        self.request('reconcile',dict(run_id=run['id'],decision='release',instances={}))
        self.assertEqual(self.run_view(run)['state'],'ABANDONED');self.assertTrue(self.h.local.instances['alpha']['process_running'])

    def test_agent_disconnect_preserves_ownership_and_cannot_affect_mission_runtime(self):
        run=self.launch(spec(components=[component('alpha')]));self.ready(run)
        self.h.agent.stop_event.set();self.h.agent.thread.join(3)
        with self.h.service.registry.lock:self.h.service.registry.agents['desktop']['seen']-=10
        wait(lambda:self.run_view(run)['state']=='FAILED')
        self.assertTrue(self.h.local.instances['alpha']['process_running'])
        self.assertTrue(self.h.service.workspaces.data['leases']['desktop/alpha']['owners'])
        self.assertEqual(self.h.lab.runtime.views(),[])

    def test_template_context_requirements_and_persistence(self):
        value=self.request('template',dict(template_id='rover-navigation',context=CTX))
        self.assertEqual([c['tool_id'] for c in value['components']],['ros2','nav2','rviz2'])
        self.request('save',dict(spec=value))
        disk=self.h.service.store.load('workspaces.json',{});self.assertEqual(disk['definitions']['rover-navigation'],value)
        self.assertEqual(self.h.api('/api/workspaces/template',dict(template_id='uav-ground-station',context=CTX))[0],409)

    def test_stop_before_delivery_cancels_launch_without_creating_process(self):
        self.h.agent.stop_event.set();self.h.agent.thread.join(3);self.h.agent.worker.join(3)
        run=self.launch(spec(components=[component('alpha')]))
        wait(lambda:self.run_view(run)['components'][0]['job_id'])
        self.stop(run);self.assertFalse(self.h.local.instances)
        self.assertEqual(next(iter(self.h.service.registry.jobs.values()))['state'],'CANCELLED')

    def test_retry_after_data_becomes_available_reuses_the_existing_process(self):
        flag=self.h.directory/'data-ready'
        self.h.local.registry['alpha']['profiles']['default']['ready']={'argv':[sys.executable,'-c',f'from pathlib import Path;print("ready" if Path({str(flag)!r}).exists() else "waiting")'],'contains':['ready'],'timeout_s':1}
        self.h.local.registry['alpha']['profiles']['default']['startup_timeout_s']=20
        run=self.launch(spec(components=[component('alpha',timeout_s=1)]));wait(lambda:self.run_view(run)['state']=='FAILED')
        flag.touch();self.request('retry',{'run_id':run['id']});self.ready(run)
        self.assertEqual(self.h.local.counter,1);self.stop(run)

    def test_multiple_agents_dependency_orchestration(self):
        store=Store(self.h.directory/'server-state');self.addCleanup(store.close)
        local=LocalTools([tool('gamma',code='import time;print("gamma",flush=True);time.sleep(120)')],store)
        agent=Agent('server','Server','server',self.h.agent.endpoint,self.h.channel.credentials['server'],local,interval_s=.1)
        agent.start();self.addCleanup(agent.close)
        wait(lambda:len(self.h.service.registry.agents)==2)
        run=self.launch(spec(components=[component('alpha'),component('gamma',['alpha'],agent_id='server')]))
        self.ready(run);self.assertEqual(self.h.local.counter,1);self.assertEqual(local.counter,1)
        self.stop(run);wait(lambda:not local.instances['gamma']['process_running'])

    def test_parallel_http_launch_and_stop_do_not_duplicate_instances(self):
        from concurrent.futures import ThreadPoolExecutor
        self.request('save',{'spec':spec(components=[component('alpha')])})
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:self.h.api('/api/workspaces/launch',{'id':'work'}),range(2)))
        self.assertEqual(sorted(code for code,_ in results),[200,409])
        run=next(body['result'] for code,body in results if code==200);self.ready(run)
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _:self.h.api('/api/workspaces/stop',{'run_id':run['id']}),range(2)))
        self.assertTrue(all(code==200 for code,_ in results));wait(lambda:self.run_view(run)['state']=='STOPPED')
        self.assertEqual(self.h.local.counter,1)


if __name__=='__main__':unittest.main()
