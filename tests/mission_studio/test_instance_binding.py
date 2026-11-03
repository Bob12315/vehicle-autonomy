"""Explicit instance binding on the real HTTP/Studio/runtime admission path."""
from copy import deepcopy
from dataclasses import replace
import time
import unittest

from tests.web_ui.helpers import Harness, FixtureDriver
from tests.mission_studio.test_compiler import definition, node, edge
from vehicle_autonomy.contracts.core.primitives import ResourceVersion


class InstanceBindingTests(unittest.TestCase):
    def setUp(self):
        self.h=Harness(standard=True);self.addCleanup(self.h.close)
        self.client=self.h.client();self.client.login()
        self.second=FixtureDriver('rover');self.second.session='second-session'
        self.h.lab.drivers['B']=self.second;self.h.lab.runtime.drivers['B']=self.second

    def api(self,op,p=None):
        code,value,_=self.client.call('/api/studio-b/'+op.replace('.','/'),p)
        return code,value

    def ok(self,op,p=None):
        code,value=self.api(op,p);self.assertEqual(code,200,value);return value['result']

    def publish(self,*,identifier='bound',action='GetVehicleState',wait=0,supported=None):
        nodes=[node('start','Start'),node('work','Action',action_type=action),node('end','End')]
        edges=[edge('start','work'),edge('work','end')]
        if wait:
            nodes.insert(2,node('wait','Wait',parameters={'duration_s':wait}))
            edges=[edge('start','work'),edge('work','wait'),edge('wait','end')]
        if action=='Goto':nodes[1]['parameters']={'x_m':0.,'y_m':0.,'z_m':0.}
        d=definition(nodes,edges);d.update(mission_id=identifier,target='rover',supported_vehicles=supported or ['rover'])
        self.ok('draft.save',dict(definition=d,expected_revision=0))
        return self.ok('draft.publish',dict(mission_id=identifier,revision=1))

    def request(self,pub,target='B'):
        binding=next(v['binding'] for v in self.ok('catalog')['vehicles'] if v['target']==target)
        self.assertIsNotNone(binding)
        return dict(publication=pub['key'],definition_hash=pub['definition_hash'],binding=binding,allow_send=False)

    def finish(self,run):
        end=time.monotonic()+4
        while time.monotonic()<end:
            v=self.ok('run.get',{'id':run['id']})
            if v['state'] in ('SUCCEEDED','UNKNOWN','CANCELLED','FAILED'):return v
            time.sleep(.03)
        self.fail('Mission did not finish')

    def test_no_implicit_target_and_hash_or_identity_mismatch_creates_no_actions(self):
        pub=self.publish()
        self.assertEqual(self.api('run.start',{'publication':pub['key']})[0],409)
        for field in ('target','vehicle_id','system_id','world','simulation_session','epoch','session_id','generation','kind'):
            p=self.request(pub);p['binding'][field]='wrong'
            self.assertEqual(self.api('run.start',p)[0],409,field)
        p=self.request(pub);p['definition_hash']='wrong'
        self.assertEqual(self.api('run.start',p)[0],409)
        self.assertFalse(self.h.lab.runtime.views());self.assertFalse(self.second.writes)

    def test_recompile_B_preserves_original_publication_and_readonly_send(self):
        pub=self.publish();before=deepcopy(pub)
        # The legacy runner already saved this exact immutable version before
        # explicit instance binding existed; rebinding must remain compatible.
        self.h.lab.journal.save_version(pub['compiled'])
        r=self.ok('run.start',self.request(pub));v=self.finish(r)
        self.assertEqual(v['state'],'SUCCEEDED',v['error']);self.assertEqual(v['target'],'B')
        self.assertEqual(v['execution_binding']['instance']['session_id'],'second-session')
        self.assertTrue(all(self.h.lab.runtime.view(i)['target']=='B' for i in v['action_ids']))
        self.assertEqual(self.h.lab.studio.library.snapshot()['publications'][pub['key']],before)
        self.assertEqual(self.h.lab.journal.data['versions'][pub['key']]['target'],'rover')
        self.assertFalse(self.second.writes);self.assertFalse(self.second.opened)
        a=self.finish(self.ok('run.start',self.request(pub,'rover')))
        self.assertEqual(a['state'],'SUCCEEDED')
        self.assertEqual(self.h.lab.journal.data['versions'][pub['key']]['target'],'rover')

    def test_removed_instance_never_rebinds_replacement_or_remains_in_catalog(self):
        pub=self.publish();old=self.request(pub)
        self.h.lab._retired_simulation_targets={'B'}
        c=FixtureDriver('rover');self.h.lab.drivers['C']=c;self.h.lab.runtime.drivers['C']=c
        self.assertNotIn('B',[v['target'] for v in self.ok('catalog')['vehicles']])
        self.assertEqual(self.api('run.start',old)[0],409)
        self.assertFalse(c.writes)
        self.assertEqual(self.finish(self.ok('run.start',self.request(pub,'C')))['state'],'SUCCEEDED')

    def test_publication_validation_witness_can_retire_without_rewriting_version(self):
        pub=self.publish();self.h.lab._retired_simulation_targets={'rover'}
        v=self.finish(self.ok('run.start',self.request(pub)))
        self.assertEqual(v['state'],'SUCCEEDED',v['error'])
        self.assertEqual(self.h.lab.studio.library.snapshot()['publications'][pub['key']],pub)

    def test_selected_provider_binding_is_rechecked(self):
        from types import SimpleNamespace
        from tests.action_system.test_runtime import Parameters,Factory
        from vehicle_autonomy.contracts.decision import ActionSpec
        registry=self.h.lab.registry
        registry.register_typed(ActionSpec('ProviderQuery',Parameters,external_lifecycle='managed'),Factory())
        self.h.drivers['rover'].resource_store=SimpleNamespace(binding=lambda:dict(provider_id='validated-provider'))
        self.second.resource_store=SimpleNamespace(binding=lambda:None)
        pub=self.publish(action='ProviderQuery')
        self.assertEqual(self.api('run.start',self.request(pub))[0],409)
        self.assertFalse(self.h.lab.runtime.views());self.assertFalse(self.second.writes)

    def test_link_epoch_and_generation_and_freshness_changes_reject_before_submit(self):
        pub=self.publish();p=self.request(pub)
        self.second.session='reconnected'
        self.assertEqual(self.api('run.start',p)[0],409)
        p=self.request(pub);snapshot=self.second.snapshot
        self.second.snapshot=lambda:replace(snapshot(),version=ResourceVersion('new-world-generation',1))
        self.assertEqual(self.api('run.start',p)[0],409)
        p=self.request(pub);self.second.fresh=False
        self.assertEqual(self.api('run.start',p)[0],409)
        self.assertFalse(self.h.lab.runtime.views())

    def test_incompatible_type_capabilities_and_parameters_revalidated_for_selected_target(self):
        pub=self.publish(action='Goto')
        self.h.lab.drivers['air']=FixtureDriver('copter');self.h.lab.runtime.drivers['air']=self.h.lab.drivers['air']
        self.assertEqual(self.api('run.start',self.request(pub,'air'))[0],409)
        self.second.context=lambda:replace(FixtureDriver('rover').context(),capabilities=frozenset())
        self.assertEqual(self.api('run.start',self.request(pub))[0],409)
        self.assertFalse(self.h.lab.runtime.views())

    def test_vehicle_specific_parameter_bounds_are_recompiled_not_copied(self):
        for kind in ('plane','copter'):
            driver=FixtureDriver(kind);self.h.lab.drivers[kind]=driver;self.h.lab.runtime.drivers[kind]=driver
        d=definition();d.update(mission_id='aircraft',target='plane',supported_vehicles=['plane','copter'])
        d['nodes'][1].update(action_type='Takeoff',parameters={'height_m':50.})
        self.ok('draft.save',dict(definition=d,expected_revision=0))
        pub=self.ok('draft.publish',dict(mission_id='aircraft',revision=1))
        self.assertEqual(self.api('run.start',self.request(pub,'copter'))[0],409)
        self.assertFalse(self.h.lab.runtime.views())

    def test_transitive_pinned_submission_recompiles_for_B_after_source_retires(self):
        child=self.publish(identifier='child')
        d=definition();d.update(mission_id='parent',target='rover')
        d['nodes'][1]=node('work','SubMission',sub_mission={'mission_id':'child','version':'1.0.0'})
        self.ok('draft.save',dict(definition=d,expected_revision=0))
        pub=self.ok('draft.publish',dict(mission_id='parent',revision=1))
        self.h.lab._retired_simulation_targets={'rover'}
        v=self.finish(self.ok('run.start',self.request(pub)))
        self.assertEqual(v['state'],'SUCCEEDED',v['error'])
        self.assertTrue(all(self.h.lab.runtime.view(a)['target']=='B' for a in v['action_ids']))
        self.assertEqual(self.h.lab.studio.library.snapshot()['publications'][child['key']],child)

    def test_running_binding_cannot_mutate_and_epoch_loss_fences_waiting_mission(self):
        pub=self.publish(wait=2);p=self.request(pub);r=self.ok('run.start',p)
        self.assertEqual(self.api('run.debug',dict(id=r['id'],operation='rebind',parameters={'target':'rover'}))[0],409)
        self.second.session='changed-during-run'
        v=self.finish(r);self.assertEqual(v['state'],'UNKNOWN');self.assertEqual(v['target'],'B')
        self.assertEqual(v['execution_binding']['instance'],p['binding'])
        self.assertFalse(self.second.writes)

    def test_templates_clone_import_restore_clear_instance_and_cannot_validate_until_selected(self):
        pub=self.publish()
        self.h.lab.studio.library.template('reuse',pub['definition'])
        for op,source in (('template.apply','reuse'),('draft.clone','bound'),('draft.restore',pub['key'])):
            d=self.ok(op,dict(source=source,new_mission_id=op.replace('.','_')))['definition']
            self.assertEqual(d['target'],'')
            self.assertEqual(self.api('draft.validate',dict(mission_id=d['mission_id'],revision=d['revision']))[0],409)
        d=self.ok('draft.import',dict(definition=pub['definition'],new_mission_id='imported'))['definition']
        self.assertEqual(d['target'],'')
        self.assertEqual(pub,self.h.lab.studio.library.snapshot()['publications'][pub['key']])

    def test_two_authenticated_browsers_bind_different_instances_and_resource_conflict_rejects(self):
        pub=self.publish(wait=.6)
        other=self.h.client();other.login()
        a=self.request(pub,'rover');b=self.request(pub,'B')
        r=self.ok('run.start',a)
        code,data,_=other.call('/api/studio-b/run/start',b);self.assertEqual(code,200,data)
        identifiers=set(self.h.lab.runtime._records)
        self.assertEqual(self.api('run.start',a)[0],409)
        self.assertEqual(set(self.h.lab.runtime._records),identifiers)
        self.assertEqual(self.finish(r)['state'],'SUCCEEDED')
        self.assertEqual(self.finish(data['result'])['state'],'SUCCEEDED')
