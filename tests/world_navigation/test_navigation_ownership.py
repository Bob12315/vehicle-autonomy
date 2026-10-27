from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from vehicle_autonomy.app.bootstrap.action_ownership import OwnedActionSimulation
from vehicle_autonomy.app.bootstrap.navigation_ownership import OwnedNavigationIdentity,RESOURCES
from vehicle_autonomy.app.bootstrap.native_navigation_processes import NativeNavigationProcesses
from vehicle_autonomy.contracts.action import ActionSafety
from vehicle_autonomy.contracts.action_ports import ActionAdmissionRejected
from vehicle_autonomy.engine.action.provider_identity import ProviderRegistry
from vehicle_autonomy.engine.action.resources import PersistentResources

class NavigationOwnershipTests(unittest.TestCase):
    def test_native_identity_cannot_be_reset_with_directory_scope_or_epoch_alias(self):
        with TemporaryDirectory() as directory:
            base=Path(directory);root=base/'actual-simulation';root.mkdir(mode=0o700)
            # Controlled unit proof; real PID/epoch proof is exercised by the
            # isolated signed SITL managed-native integration fixture.
            proof=OwnedActionSimulation.__new__(OwnedActionSimulation);proof.kind='rover';proof.root=root;proof.manifest={'world':'actual-physical-world'};proof.assert_alive=lambda:None
            with patch.object(ProviderRegistry,'_root',base/'trusted-registry'):
                ProviderRegistry.initialize();identity=OwnedNavigationIdentity(proof);store=identity.provision()
                self.assertEqual(identity.load().binding(),store.binding());self.assertEqual(store.bound_resources(),RESOURCES)
                with self.assertRaises(ValueError):identity.provision()
                data=identity.identity()
                for scope in ('another-scope','owned-native-navigation'):
                    with self.assertRaises(ValueError):PersistentResources.initialize(base/('other-'+scope),lambda:ActionSafety(True,evidence={'quiescent':True,**data}),scope=scope,resources=RESOURCES)
                proof.manifest['world']='caller-changed-epoch'
                alias=OwnedNavigationIdentity(proof);self.assertEqual(alias.provider_id,identity.provider_id)
                with self.assertRaises(ValueError):alias.load()
    def test_unmanaged_native_cohort_cannot_spawn_or_create_state(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)/'should-not-exist'
            with self.assertRaises(ActionAdmissionRejected):NativeNavigationProcesses(root,'/nav2_test',{})
            self.assertFalse(root.exists())
