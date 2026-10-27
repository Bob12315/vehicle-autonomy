"""Logical Goal result must be prompt without releasing a live producer ledger."""
from dataclasses import dataclass
import json,os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from vehicle_autonomy.actions.navigation.native_job import NativeNavigationJob
from vehicle_autonomy.app.bootstrap.action_ownership import OwnedActionSimulation
from vehicle_autonomy.app.bootstrap.navigation_ownership import OwnedNavigationIdentity,RESOURCES
from vehicle_autonomy.contracts.decision import ActionSpec
from vehicle_autonomy.engine.action.external_lifecycle import ExternalLifecycle
from vehicle_autonomy.engine.action.provider_identity import ProviderRegistry
from vehicle_autonomy.engine.action.resources import ActionResources

@dataclass(frozen=True)
class Parameters:
    pass

class NativeTerminalLifecycleTests(unittest.TestCase):
    def test_known_result_precedes_shutdown_but_resource_stays_occupied(self):
        with TemporaryDirectory() as directory:
            base=Path(directory);root=base/'owned';root.mkdir(mode=0o700)
            proof=OwnedActionSimulation.__new__(OwnedActionSimulation);proof.kind='rover';proof.root=root;proof.manifest={'world':'controlled-native-unit'};proof.assert_alive=lambda:None
            stopping=Event();allow_stop=Event();job=None
            class ControlledCohort:
                def __init__(self,*args):pass
                def start(self,**kwargs):pass
                def source_receiver(self,address):return SimpleNamespace(pid=os.getpid())
                def goal_worker(self,path):
                    value=json.loads(Path(path).read_text());terminal={'goal_id':value['goal']['goal_id'],'state':'SUCCEEDED'}
                    (Path(path).parent/'terminal.json').write_text(json.dumps(terminal))
                    return SimpleNamespace(poll=lambda:None) # DDS shutdown is still live.
                def assert_alive(self):pass
                def stop(self):stopping.set();return allow_stop.wait(4)
            with patch.object(ProviderRegistry,'_root',base/'registry'):
                ProviderRegistry.initialize();identity=OwnedNavigationIdentity(proof);store=identity.provision()
                resources=ActionResources();self.assertTrue(resources.acquire('owner','rover',RESOURCES,persistent=True,external_store=store));resources.started('owner')
                spec=ActionSpec('NativeTest',Parameters,resources=RESOURCES,external_lifecycle='managed')
                lifecycle=ExternalLifecycle(spec,store,'owner',resources.runtime_id,lambda:True)
                goal=dict(goal_id='1'*32,action_id='owner',target_id='rover',vehicle_session='session',world_generation='world',map_epoch='map',x_m=0.,y_m=0.,yaw_rad=0.,provider_id=identity.provider_id,provider_epoch=identity.provider_epoch)
                try:
                    with lifecycle.callback():job=lifecycle.start(lambda:NativeNavigationJob(identity,goal,security_environment={},world_name=identity.provider_epoch,clock_domain='host-monotonic-simulation',cohort_factory=ControlledCohort))
                    self.assertTrue(stopping.wait(2),'logical result was hidden until process death')
                    value=job.poll();self.assertEqual(value['state'],'RUNNING')
                    self.assertEqual(value['feedback']['native_result']['state'],'SUCCEEDED')
                    self.assertFalse(lifecycle.assess().release_safe)
                    self.assertFalse(resources.acquire('successor','rover',RESOURCES,persistent=True,external_store=store))
                    allow_stop.set();job._thread.join(2)
                    self.assertEqual(job.poll()['state'],'SUCCEEDED');self.assertTrue(lifecycle.assess().release_safe)
                    resources.release('owner',safety=lifecycle.assess())
                    self.assertTrue(resources.acquire('successor','rover',RESOURCES,persistent=True,external_store=store))
                    resources.release('successor',no_effects=True)
                finally:
                    allow_stop.set()
                    if job:job.cancel();job._thread.join(4)
