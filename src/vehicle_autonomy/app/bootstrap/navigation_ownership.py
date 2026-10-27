"""Nav2's safety identity is the actual owned vehicle epoch, never a UI alias.

Uses the existing fixed deployment ProviderRegistry/ledger. This does not grant
SEND or replace the vehicle Authority lease. No signing key content is read.
"""
import os
from pathlib import Path
from vehicle_autonomy.app.bootstrap.action_ownership import OwnedActionSimulation
from vehicle_autonomy.contracts.action import ActionResource,ActionSafety
from vehicle_autonomy.engine.action.resources import PersistentResources

from vehicle_autonomy.contracts.algorithms import NATIVE_NAVIGATION_RESOURCES as RESOURCES


class OwnedNavigationIdentity:
    def __init__(self,ownership):
        if not isinstance(ownership,OwnedActionSimulation) or ownership.kind!='rover':raise ValueError('actual owned Rover proof required')
        ownership.assert_alive();self.ownership=ownership;self.root=ownership.root
        info=self.root.stat();self._identity=(info.st_dev,info.st_ino)
        self.provider_id=f'owned-native-navigation:{os.getuid()}:{info.st_dev}:{info.st_ino}'
        self.provider_epoch=ownership.manifest['world']
        self.locator=f'native:{os.getuid()}:owned-navigation:{info.st_dev}:{info.st_ino}'
        self.directory=self.root/'native-navigation-resources';self.scope='owned-native-navigation'
    def identity(self):
        self.ownership.assert_alive()
        if (self.root.stat().st_dev,self.root.stat().st_ino)!=self._identity:raise ValueError('navigation provider physical epoch changed')
        return dict(provider_id=self.provider_id,provider_epoch=self.provider_epoch,resource_id='jobs',protocol='native',locator=self.locator)
    def provision(self):
        # Explicit first deployment only. A previous cohort directory is not a
        # fresh/quiescent proof; missing established state cannot be reset here.
        if (self.root/'native-navigation-jobs').exists():raise ValueError('existing native jobs require controlled recovery')
        identity=self.identity()
        store=PersistentResources.initialize(self.directory,lambda:ActionSafety(True,evidence=dict(quiescent=True,**identity)),scope=self.scope,resources=RESOURCES)
        (self.root/'native-navigation-jobs').mkdir(mode=0o700)
        return store
    def load(self):
        store=PersistentResources(self.directory,self.scope);binding=store.binding()
        if any(binding[k]!=v for k,v in self.identity().items()) or store.bound_resources()!=RESOURCES:raise ValueError('navigation identity/ledger mismatch')
        return store
