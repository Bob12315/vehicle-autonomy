from dataclasses import dataclass
import json,secrets,time,unittest
from urllib.request import Request,urlopen

from tests.web_ui.helpers import Harness
from vehicle_autonomy.contracts.decision import ActionSpec
from tests.action_system.test_runtime import Factory
from .helpers import gps


@dataclass(frozen=True)
class Goal:
    x_m:float=0.
    y_m:float=0.
    z_m:float=0.


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.h=Harness();self.addCleanup(self.h.close);gps(self.h);self.c=self.h.client();self.c.login()
        self.h.server.visualization_token=secrets.token_urlsafe(32);self.cap={'Authorization':'Bearer '+self.h.server.visualization_token}
        self.h.lab.registry.register_typed(ActionSpec('Goto',Goal),Factory())
    def proposal(self,**kw):
        source=self.c.call('/api/visualization/state?target=rover')[1]['result']
        return dict(id=secrets.token_hex(12),target='rover',epoch=source['epoch'],frame='odom',position=[1.,0.,0.],orientation=[0.,0.,0.,1.])|kw
    def test_capability_reads_only_bounded_state_and_cannot_execute_or_log_in(self):
        self.assertEqual(self.h.client().call('/api/visualization/state?target=rover')[0],401)
        code,data,_=self.h.client().call('/api/visualization/state?target=rover',headers=self.cap);self.assertEqual(code,200);self.assertTrue(data['result']['valid'])
        for route in ('/api/control/state','/api/instances','/api/auth/session'):
            self.assertEqual(self.h.client().call(route,headers=self.cap)[0],401,route)
        for route in ('/api/manual/action','/api/run','/api/visualization/confirm'):
            self.assertEqual(self.h.client().call(route,{},headers=self.cap)[0],401,route)
        self.assertFalse(self.h.lab.runtime.views())
    def test_ros_proposal_is_inert_and_execution_requires_current_control_and_confirmation(self):
        p=self.proposal();headers=self.cap|{'X-VAF-Visualization':'candidate-v1'}
        self.assertEqual(self.h.client().call('/api/visualization/candidates',p,headers=headers)[0],200)
        self.assertFalse(self.h.lab.runtime.views());self.assertFalse(self.h.drivers['rover'].writes)
        execute=dict(id=p['id'],target='rover',allow_send=True)
        self.assertEqual(self.c.call('/api/visualization/confirm',execute)[0],409)
        self.c.acquire();self.assertEqual(self.c.call('/api/visualization/confirm',execute|dict(allow_send=False))[0],409)
        self.assertEqual(self.c.call('/api/visualization/confirm',execute)[0],200)
        self.assertEqual(self.c.call('/api/visualization/confirm',execute)[0],409);self.assertEqual(len(self.h.lab.runtime.views()),1)
    def test_wrong_origin_frame_epoch_pose_and_csrf_are_rejected(self):
        p=self.proposal()
        for change in (dict(frame='earth'),dict(epoch='old'),dict(position=[float('nan'),0,0]),dict(orientation=[0.,0.,0.,0.])):
            self.assertIn(self.c.call('/api/visualization/candidates',p|change)[0],(400,409))
        self.assertEqual(self.c.call('/api/visualization/candidates',p,headers={'X-VAF-CSRF':''})[0],403)
        self.assertEqual(self.h.client().call('/api/visualization/candidates',p,headers=self.cap)[0],409)
        self.assertEqual(self.h.client().call('/api/visualization/state?target=rover',headers=self.cap|{'Origin':'http://bad.invalid'})[0],403)
        self.assertFalse(self.h.lab.runtime.views())
    def test_stale_localization_expiration_and_reconnection_fence_confirmation(self):
        p=self.proposal();self.c.call('/api/visualization/candidates',p);self.c.acquire();self.h.drivers['rover'].fresh=False
        self.assertEqual(self.c.call('/api/visualization/confirm',dict(id=p['id'],target='rover',allow_send=True))[0],409)
        self.h.drivers['rover'].fresh=True;self.h.lab.visualization_goals.clock=lambda:time.monotonic()+31
        self.assertEqual(self.c.call('/api/visualization/confirm',dict(id=p['id'],target='rover',allow_send=True))[0],409)
        self.assertFalse(self.h.lab.runtime.views())
    def test_proposals_are_idempotent_and_reused_identity_cannot_change_coordinates(self):
        p=self.proposal();a=self.c.call('/api/visualization/candidates',p);b=self.c.call('/api/visualization/candidates',p)
        self.assertEqual(a[0],200);self.assertEqual(b[1]['result']['id'],p['id']);self.assertEqual(len(self.c.call('/api/visualization/candidates?target=rover')[1]['result']),1)
        self.assertEqual(self.c.call('/api/visualization/candidates',p|dict(position=[2.,0.,0.]))[0],409)
    def test_aircraft_proposals_are_preview_only(self):
        h=Harness(kinds=('copter','plane'));self.addCleanup(h.close);gps(h);c=h.client();c.login()
        for kind in ('copter','plane'):
            source=c.call('/api/visualization/state?target='+kind)[1]['result'];p=self.proposal()|dict(target=kind,epoch=source['epoch'])
            code,data,_=c.call('/api/visualization/candidates',p);self.assertEqual(code,200,data);self.assertFalse(data['result']['executable'])
        self.assertFalse(h.lab.runtime.views())
    def test_map_goal_is_preview_only_and_cannot_execute_without_qualified_transform(self):
        p=self.proposal(frame='map',ros_frame='slam/map');code,data,_=self.c.call('/api/visualization/candidates',p)
        self.assertEqual(code,200);self.assertFalse(data['result']['executable']);self.c.acquire()
        self.assertEqual(self.c.call('/api/visualization/confirm',dict(id=p['id'],target='rover',allow_send=True))[0],409);self.assertFalse(self.h.lab.runtime.views())
    def test_proposal_budget_is_bounded_without_evicting_live_goals(self):
        clock=[100.];self.h.lab.visualization_goals.clock=lambda:clock[0]
        for _ in range(64):
            clock[0]+=.21;self.assertEqual(self.c.call('/api/visualization/candidates',self.proposal())[0],200)
        clock[0]+=.21;self.assertEqual(self.c.call('/api/visualization/candidates',self.proposal())[0],409)
        self.assertFalse(self.h.lab.runtime.views())
