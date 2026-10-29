"""HTTP/auth contract checks; these fixtures do not qualify native simulation."""
from unittest.mock import patch
import unittest

from tests.web_ui.helpers import Harness


class UniversalSimulationWebTests(unittest.TestCase):
    def setUp(self):
        self.h=Harness(kinds=('rover','copter'))
        self.addCleanup(self.h.close)
        self.a=self.h.client();self.a.login()
        self.b=self.h.client();self.b.login()
        self.manager=self.h.lab.simulation_manager
        self.record=dict(id='sim-'+'1'*32,state='RUNNING',vehicles=[
            dict(id='vehicle-one',kind='rover',target='rover',state='RUNNING'),
            dict(id='vehicle-two',kind='copter',target='copter',state='RUNNING')])

    def test_new_routes_are_fixed_and_share_authentication(self):
        unknown=self.h.client()
        self.assertEqual(unknown.call('/api/simulation/vehicles')[0],401)
        with patch.object(self.manager,'handle',return_value=[]) as handle:
            self.assertEqual(self.a.call('/api/simulation/vehicles')[0],200)
            handle.assert_called_once_with('simulation.vehicles',{})
        with patch.object(self.manager,'sample',return_value=self.record),patch.object(self.manager,'handle',return_value={'accepted':True}) as handle:
            for operation,payload in (
                ('switch',dict(id=self.record['id'],scene_id='R04',spawns={})),
                ('add_vehicle',dict(id=self.record['id'],vehicle={'kind':'rover','spawn':{'preset_id':'safe'}})),
                ('remove_vehicle',dict(id=self.record['id'],vehicle_id='vehicle-one'))):
                self.assertEqual(self.a.call('/api/simulation/'+operation,payload)[0],200)
                handle.assert_called_with('simulation.'+operation,payload)
                self.assertEqual(self.a.call('/api/simulation/'+operation,payload,headers={'X-VAF-CSRF':''})[0],403)
                self.assertEqual(self.a.call('/api/simulation/'+operation,payload,headers={'Origin':'http://evil.invalid'})[0],403)
        self.assertFalse(any(d.writes for d in self.h.drivers.values()))

    def test_world_operations_cannot_cross_either_vehicle_owner(self):
        self.a.acquire('rover');self.b.acquire('copter')
        with patch.object(self.manager,'sample',return_value=self.record),patch.object(self.manager,'handle') as handle:
            for operation in ('stop','pause','resume','reset','switch','add_vehicle'):
                for client in (self.a,self.b):
                    code,data,_=client.call('/api/simulation/'+operation,{'id':self.record['id']})
                    self.assertEqual(code,409,(operation,data))
                    self.assertIn('original control page',data['error'])
                headers={'Authorization':'Bearer '+self.h.token,'X-VAF-CSRF':self.h.token}
                self.assertEqual(self.b.call('/api/simulation/'+operation,{'id':self.record['id']},headers=headers)[0],409)
            handle.assert_not_called()
        self.assertFalse(any(d.writes for d in self.h.drivers.values()))

    def test_selected_vehicle_mutation_is_fenced_to_its_world_and_owner(self):
        self.a.acquire('rover');self.b.acquire('copter')
        with patch.object(self.manager,'sample',return_value=self.record),patch.object(self.manager,'handle',return_value={'accepted':True}) as handle:
            for operation in ('remove_vehicle','test'):
                path='/api/simulation/'+operation
                payload={'id':self.record['id'],'vehicle_id':'vehicle-one'}
                self.assertEqual(self.a.call(path,payload)[0],200)
                self.assertEqual(self.b.call(path,payload)[0],409)
                self.assertEqual(self.a.call(path,dict(payload,vehicle_id='vehicle-from-another-world'))[0],409)
                self.assertEqual(self.a.call(path,{'id':self.record['id']})[0],409)
            self.assertEqual(handle.call_count,2)
        self.assertFalse(any(d.writes for d in self.h.drivers.values()))

    def test_selected_receive_fault_cannot_indirectly_retire_another_owner(self):
        self.a.acquire('rover');self.b.acquire('copter')
        payload=dict(id=self.record['id'],vehicle_id='vehicle-one',settings={'freeze':True})
        with patch.object(self.manager,'sample',return_value=self.record),patch.object(self.manager,'handle',return_value={'accepted':True}) as handle:
            self.assertEqual(self.a.call('/api/simulation/fault',payload)[0],409)
            self.assertEqual(self.b.call('/api/simulation/fault',payload)[0],409)
            handle.assert_not_called()
            self.assertEqual(self.b.call('/api/control/release',{'target':'copter'})[0],200)
            self.assertEqual(self.a.call('/api/simulation/fault',payload)[0],200)
            handle.assert_called_once_with('simulation.fault',payload)
        self.assertFalse(any(d.writes for d in self.h.drivers.values()))

    def test_explicit_release_allows_world_change_without_transferring_control(self):
        self.a.acquire('rover');self.b.acquire('copter')
        self.assertEqual(self.a.call('/api/control/release',{'target':'rover'})[0],200)
        self.assertEqual(self.b.call('/api/control/release',{'target':'copter'})[0],200)
        with patch.object(self.manager,'sample',return_value=self.record),patch.object(self.manager,'handle',return_value={'status':'SWITCHING'}) as handle:
            self.assertEqual(self.a.call('/api/simulation/switch',{'id':self.record['id'],'scene_id':'R04'})[0],200)
            handle.assert_called_once()
        self.assertFalse(self.h.lab.operator_controls.records)
        self.assertFalse(any(d.writes for d in self.h.drivers.values()))

    def test_retirement_fence_rejects_new_scopes_but_allows_query_and_release(self):
        from vehicle_autonomy.actions.catalog import register_standard
        register_standard(self.h.lab.registry)
        self.a.acquire('rover')
        headers={'Authorization':'Bearer '+self.h.token,'X-VAF-CSRF':self.h.token}
        with patch.object(self.manager,'retiring_targets',return_value={'rover'},create=True):
            # An owner may still exit, but cannot create another action while
            # asynchronous safe retirement is between dispatch and detach.
            code,data,_=self.a.call('/api/manual/action',dict(target='rover',name='ok',parameters={},allow_send=True))
            self.assertEqual(code,409,data);self.assertIn('retiring',data['error'])
            self.assertEqual(self.a.call('/api/control/release',{'target':'rover'})[0],200)
            code,data,_=self.a.call('/api/control/acquire',{'target':'rover'})
            self.assertEqual(code,409,data);self.assertIn('retiring',data['error'])
            code,data,_=self.a.call('/api/missions/start',{'spec':{'target':'rover'}},headers=headers)
            self.assertEqual(code,409,data);self.assertIn('retiring',data['error'])
            code,data,_=self.a.call('/api/manual/start',dict(target='rover',name='Drive',parameters={},allow_send=True),headers=headers)
            self.assertEqual(code,409,data);self.assertIn('retiring',data['error'])
            code,data,_=self.a.call('/api/run',dict(target='rover',name='ok',parameters={},allow_send=True),headers=headers)
            self.assertEqual(code,409,data);self.assertIn('retiring',data['error'])
            code,data,_=self.a.call('/api/manual/action',dict(target='rover',name='GetVehicleState',parameters={},allow_send=False),headers=headers)
            self.assertEqual(code,200,data)
            self.assertEqual(data['result']['kind'],'Query')
        self.assertFalse(any(d.writes for d in self.h.drivers.values()))

    def test_ui_exposes_independent_vehicle_identity_and_reuses_control_page(self):
        html=self.a.call('/simulation')[1].decode()
        script=self.a.call('/simulation-center.js')[1].decode()
        for identifier in ('current-vehicle','session-vehicles','vehicle-instances','primary-spawn','switch-progress','switch-spawns','vehicle-definition-output'):
            self.assertIn('id="'+identifier+'"',html)
        for field in ('vehicle_id','system_id','fingerprint','definition_version','heading_deg','preset_id','slot_id'):
            self.assertIn(field,script)
        self.assertIn("'/control'+(target?'#'+encodeURIComponent(target)",script)
        self.assertIn('window.VAFAuth.api',script)
        for forbidden in ('localStorage','sessionStorage','Bearer ','innerHTML','/api/manual/action','/api/manual/start'):
            self.assertNotIn(forbidden,script)
        manual=self.a.call('/manual-control.js')[1].decode()
        self.assertIn('decodeURIComponent(location.hash.slice(1))',manual)
        self.assertIn('vehicles.some(v=>v.target===requested)',manual)


if __name__=='__main__':unittest.main()
