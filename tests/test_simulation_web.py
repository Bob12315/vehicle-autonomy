"""Real HTTP ingress tests; these fixtures do not qualify Gazebo or SITL."""
from pathlib import Path
import unittest
from unittest.mock import patch

from tests.web_ui.helpers import Harness


class SimulationWebTests(unittest.TestCase):
    def setUp(self):
        self.h=Harness()
        self.addCleanup(self.h.close)
        self.c=self.h.client()

    def test_simulation_page_and_api_share_existing_login(self):
        self.assertIn(self.c.call('/simulation')[0],(200,401,302,303))
        self.assertEqual(self.c.call('/api/simulation/catalog')[0],401)
        self.c.login()
        code,body,_=self.c.call('/simulation')
        self.assertEqual(code,200)
        self.assertIn('仿真中心',body.decode())
        self.assertNotIn('id="token"',body.decode())
        self.assertEqual(self.c.call('/console')[0],200)
        self.assertEqual(self.c.call('/api/simulation/catalog')[0],200)
        self.assertEqual(self.c.call('/api/simulation/sessions')[0],200)
        self.assertEqual(self.h.drivers['rover'].writes,[])

    def test_mutation_requires_session_csrf_and_same_origin(self):
        payload=dict(scene_id='R01',vehicle='none',seed=0,parameters={})
        self.assertEqual(self.c.call('/api/simulation/create',payload)[0],401)
        self.c.login()
        self.assertEqual(self.c.call('/api/simulation/create',payload,headers={'X-VAF-CSRF':''})[0],403)
        self.assertEqual(self.c.call('/api/simulation/create',payload,headers={'Origin':'http://evil.invalid'})[0],403)
        self.assertEqual(self.h.lab.simulation_manager.handle('simulation.sessions',{}),[])

    def test_http_create_and_history_are_real_manager_records(self):
        self.c.login()
        code,data,_=self.c.call('/api/simulation/create',dict(scene_id='R01',vehicle='none',seed=13,parameters={}))
        self.assertEqual(code,200,data)
        record=data['result']
        self.assertEqual(record['state'],'CREATED')
        self.assertEqual(record['scene_id'],'R01')
        code,data,_=self.c.call('/api/simulation/sessions')
        self.assertEqual(code,200)
        self.assertIn(record['id'],[s['id'] for s in data['result']])
        code,data,_=self.c.call('/api/simulation/report',dict(id=record['id']))
        self.assertEqual(code,200,data)
        self.assertEqual(self.h.drivers['rover'].writes,[])

    def test_browser_cannot_supply_shell_filesystem_path_or_send_deployment(self):
        self.c.login()
        for extra in ({'command':'touch /tmp/invalid'},{'world_path':'/tmp/world.sdf'}, {'allow_send':True}, {'argv':['gz','sim']}):
            code,data,_=self.c.call('/api/simulation/create',dict(scene_id='R01',vehicle='none',**extra))
            self.assertEqual(code,409,data)
        self.assertEqual(self.c.call('/api/simulation/logs',dict(id='../../etc/passwd'))[0],409)
        self.assertEqual(self.h.drivers['rover'].writes,[])

    def test_all_control_routes_dispatch_fixed_operations_and_idempotence(self):
        self.c.login()
        manager=self.h.lab.simulation_manager
        record=manager.create({'scene_id':'R01'})
        identifier=record['id']
        with patch.object(manager,'handle',return_value={'recorded':True}) as call:
            for op in ('start','stop','pause','resume','reset','test','logs','report','fault','install','uninstall','asset_status'):
                response=self.c.call('/api/simulation/'+op,{'id':identifier},identifier='sim-'+op)
                self.assertEqual(response[0],200,response)
                call.assert_called_with('simulation.'+op,{'id':identifier})
            first=self.c.call('/api/simulation/start',{'id':identifier},identifier='sim-start')
            self.assertEqual(first[0],200)
            self.assertEqual(call.call_count,12)
            conflict=self.c.call('/api/simulation/start',{'id':'other'},identifier='sim-start')
            self.assertEqual(conflict[0],409)


    def _owned_live_session(self):
        from threading import Event
        from types import SimpleNamespace
        from tests.test_simulation_manager import ByteFixture
        from vehicle_autonomy.app.simulation.faults import SoftwareFaultLink
        manager=self.h.lab.simulation_manager
        record=manager.create({'scene_id':'R01'})
        manager.records[record['id']].update(state='RUNNING',target='rover')
        manager.stops[record['id']]=Event()
        link=SoftwareFaultLink(ByteFixture())
        manager.owners[record['id']]=SimpleNamespace(link=link,driver=None,close=lambda:None,target='rover')
        # No process is launched by this HTTP authorization fixture.
        self.addCleanup(lambda:manager.records[record['id']].update(state='FINISHED'))
        return record['id'],link

    def test_fault_requires_the_existing_browser_control_owner(self):
        self.c.login();self.c.acquire('rover')
        second=self.h.client();second.login()
        identifier,link=self._owned_live_session()
        payload={'id':identifier,'settings':{'command_timeout':True}}
        self.assertEqual(second.call('/api/simulation/fault',payload)[0],409)
        self.assertFalse(link.settings.command_timeout)
        api_headers={'Authorization':'Bearer '+self.h.token,'X-VAF-CSRF':self.h.token}
        self.assertEqual(second.call('/api/simulation/fault',payload,headers=api_headers)[0],409)
        self.assertFalse(link.settings.command_timeout)
        self.assertEqual(self.c.call('/api/simulation/fault',payload)[0],200)
        self.assertTrue(link.settings.command_timeout)
        self.assertEqual(self.h.drivers['rover'].writes,[])

    def test_stop_requires_owner_token_but_world_only_does_not(self):
        self.c.login();self.c.acquire('rover')
        second=self.h.client();second.login()
        identifier,_=self._owned_live_session()
        self.assertEqual(second.call('/api/simulation/stop',{'id':identifier})[0],409)
        api_headers={'Authorization':'Bearer '+self.h.token,'X-VAF-CSRF':self.h.token}
        self.assertEqual(second.call('/api/simulation/stop',{'id':identifier},headers=api_headers)[0],409)
        self.assertEqual(self.h.lab.simulation_manager.records[identifier]['state'],'RUNNING')
        self.assertEqual(self.c.call('/api/simulation/stop',{'id':identifier})[0],200)
        self.assertEqual(self.h.lab.simulation_manager.records[identifier]['state'],'STOPPING')
        world=self.h.lab.simulation_manager.create({'scene_id':'R01'})
        self.assertEqual(second.call('/api/simulation/stop',{'id':world['id']})[0],200)
        self.assertEqual(self.h.drivers['rover'].writes,[])

    def test_static_ui_uses_shared_auth_and_never_injects_remote_html(self):
        self.c.login()
        for route in ('/simulation-center.js','/simulation-center.css'):
            self.assertEqual(self.c.call(route)[0],200)
        script=self.c.call('/simulation-center.js')[1].decode()
        self.assertIn('window.VAFAuth.api',script)
        for forbidden in ('localStorage','sessionStorage','Bearer ','innerHTML'):
            self.assertNotIn(forbidden,script)
        html=self.c.call('/simulation')[1].decode()
        self.assertIn('非实时渲染',html)
        self.assertIn('SEND 默认关闭',html)
        for route in ('/console','/control','/studio'):
            self.assertIn('href="/simulation"',self.c.call(route)[1].decode())
