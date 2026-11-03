import time,unittest
from vehicle_autonomy.contracts.action import ActionKind
from vehicle_autonomy.contracts.decision import ActionSpec
from tests.action_system.test_runtime import Parameters,Factory
from .helpers import Harness

class OperatorTests(unittest.TestCase):
 def setUp(self):
  self.h=Harness();self.addCleanup(self.h.close);self.c=self.h.client();self.c.login()
  self.h.lab.registry.register_typed(ActionSpec('long',Parameters,kind=ActionKind.CONTINUOUS),Factory(continuous=True))
 def wait(self,fn):
  end=time.monotonic()+3
  while time.monotonic()<end:
   value=fn()
   if value:return value
   time.sleep(.02)
  self.fail('condition timed out')
 def test_observer_cannot_mutate_and_acquisition_does_not_open_send_or_driver_scope(self):
  p=dict(name='ok',target='rover',parameters={},allow_send=True)
  self.assertEqual(self.c.call('/api/manual/action',p)[0],409)
  self.c.acquire();d=self.h.drivers['rover'];self.assertEqual(d.opened,[]);self.assertEqual(d.writes,[])
  code,data,_=self.c.call('/api/control/state');self.assertTrue(data['result']['operator_control']['rover']['mine'])
  self.assertFalse(data['result']['vehicles'][0]['system_send'])
  self.assertEqual(self.c.call('/api/manual/action',p)[0],200)
 def test_mutual_exclusion_stale_telemetry_and_epoch_change(self):
  self.c.acquire();other=self.h.client();other.login()
  self.assertEqual(other.call('/api/control/acquire',{'target':'rover'})[0],409)
  other.control=self.c.control
  self.assertEqual(other.call('/api/manual/action',dict(name='ok',target='rover'))[0],409)
  self.h.drivers['rover'].fresh=False
  self.assertEqual(self.c.call('/api/manual/action',dict(name='ok',target='rover'))[0],409)
  self.h.drivers['rover'].fresh=True;self.h.drivers['rover'].session='new-epoch'
  self.wait(lambda:'rover' not in self.h.lab.operator_controls.records)
  self.assertEqual(self.c.call('/api/control/renew',{'target':'rover'})[0],409)
  self.assertEqual(self.h.drivers['rover'].writes,[])
 def test_hardware_or_unapproved_deployment_cannot_acquire(self):
  d=self.h.drivers['rover']
  for name in ('owned','send','fresh','connected'):
   setattr(d,name,False)
   self.assertEqual(self.c.call('/api/control/acquire',{'target':'rover'})[0],409,name)
   setattr(d,name,True)
 def test_stale_telemetry_cannot_extend_managed_input_deadline_but_allows_stop(self):
  factory=Factory(continuous=True);factory.supports_input_updates=True
  self.h.lab.registry.register_typed(ActionSpec('Drive',Parameters,kind=ActionKind.CONTINUOUS),factory)
  self.c.acquire();code,data,_=self.c.call('/api/manual/start',dict(name='Drive',target='rover',parameters={},allow_send=True))
  self.assertEqual(code,200,data);session=data['result']['session'];identifier=data['result']['action']['id']
  self.wait(lambda:self.h.lab.runtime.view(identifier)['state']=='RUNNING')
  before=self.h.lab.runtime.view(identifier);self.h.drivers['rover'].fresh=False
  code,data,_=self.c.call('/api/manual/update',dict(session_id=session['id'],sequence=before['input_sequence']+1,deadline_ns=before['input_ticket'],parameters={}))
  self.assertEqual(code,409);self.assertIn('telemetry stale',data['error']);self.assertEqual(self.h.lab.runtime.view(identifier)['input_sequence'],before['input_sequence'])
  self.assertEqual(self.c.call('/api/manual/stop',dict(session_id=session['id']))[0],200)
  self.wait(lambda:self.h.lab.runtime.view(identifier)['state']=='CANCELLED')
 def test_expired_browser_reservation_requests_action_exit_and_never_resumes(self):
  self.c.acquire();code,data,_=self.c.call('/api/manual/action',dict(name='long',target='rover'));self.assertEqual(code,200)
  identifier=data['result']['id'];self.wait(lambda:self.h.lab.runtime.view(identifier)['state']=='RUNNING')
  self.h.lab.operator_controls.clock=lambda:time.monotonic()+30
  self.wait(lambda:self.h.lab.runtime.view(identifier)['state']=='CANCELLED')
  self.wait(lambda:'rover' not in self.h.lab.operator_controls.records)
  self.assertEqual(self.c.call('/api/control/renew',{'target':'rover'})[0],409)
  self.assertEqual(len(self.h.lab.runtime.views()),1)
 def test_release_and_logout_cancel_only_owned_actions(self):
  self.c.acquire();code,data,_=self.c.call('/api/manual/action',dict(name='long',target='rover'));identifier=data['result']['id']
  self.assertEqual(self.c.call('/api/control/release',{'target':'rover'})[0],200)
  self.wait(lambda:self.h.lab.runtime.view(identifier)['state']=='CANCELLED')
  self.c.control='';self.wait(lambda:'rover' not in self.h.lab.operator_controls.records)
  code,data,_=self.c.call('/api/run',dict(name='long',target='rover'));identifier=data['result']['id']
  self.assertEqual(self.c.call('/api/auth/logout',{})[0],200)
  self.wait(lambda:self.h.lab.runtime.view(identifier)['state']=='CANCELLED')
 def test_mission_and_manual_control_cannot_implicitly_preempt_each_other(self):
  graph=dict(schema_version=1,id='wait',name='wait',version='1.0.0',target='rover',root='w',nodes=[dict(id='w',type='Wait',duration_s=2.)])
  self.c.acquire();self.assertEqual(self.c.call('/api/missions/start',{'spec':graph})[0],409)
  self.c.call('/api/control/release',{'target':'rover'});self.c.control=''
  code,data,_=self.c.call('/api/missions/start',{'spec':graph});self.assertEqual(code,200,data)
  self.assertEqual(self.c.call('/api/control/acquire',{'target':'rover'})[0],409)
  self.assertEqual(self.c.call('/api/control/request-takeover',{'target':'rover','confirmed':False})[0],409)
  self.assertEqual(self.c.call('/api/control/takeover',{'target':'rover'})[0],409)
  self.assertEqual(self.c.call('/api/control/request-takeover',{'target':'rover','confirmed':True})[0],200)
  self.assertFalse(self.h.drivers['rover'].info()['system_send'])

 def test_application_exit_waits_for_action_before_retiring_simulation_and_fences_new_control(self):
  self.c.acquire();code,data,_=self.c.call('/api/manual/action',dict(name='long',target='rover'))
  self.assertEqual(code,200,data);identifier=data['result']['id']
  self.wait(lambda:self.h.lab.runtime.view(identifier)['state']=='RUNNING')
  manager=self.h.lab.simulation_manager;close=manager.close;observed=[]
  def retire():
   action=self.h.lab.runtime.view(identifier);observed.append(action['state'])
   self.assertEqual(action['state'],'CANCELLED');self.assertTrue(action['safety']['release_safe'])
   with self.assertRaisesRegex(ValueError,'closing'):
    self.h.lab._manual_action(dict(name='ok',target='rover'))
   return close()
  manager.close=retire
  self.h.lab.close()
  self.assertTrue(observed)
