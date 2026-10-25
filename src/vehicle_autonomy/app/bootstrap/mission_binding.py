"""Bind each real owned SITL epoch to one Mission journal and target label.

Uses Phase 3's fixed trusted local ProviderRegistry. An empty second journal,
an alias or a changed data-dir cannot discard that vehicle's uncertain history.
"""
import hashlib
from pathlib import Path

from vehicle_autonomy.engine.action.durable import DurableRecord, canonical
from vehicle_autonomy.engine.action.provider_identity import ProviderRegistry
from vehicle_autonomy.app.bootstrap.mission_recovery import deployment_identity


def bind_simulations(drivers,journal):
    result={};seen=set()
    for target,driver in drivers.items():
        if driver.context().target_kind not in ('rover','copter','plane'):continue
        identity=deployment_identity(driver)
        if identity is None:raise ValueError('Mission vehicle requires explicit live owned SITL identity')
        digest=hashlib.sha256(canonical(identity)).hexdigest()
        if digest in seen:raise ValueError('one owned vehicle cannot have duplicate target aliases')
        seen.add(digest)
        root=journal.path/('vehicle-'+digest)
        binding=dict(provider_id='owned-sitl:'+digest,provider_epoch=digest,resource_id='vehicle.control',
            protocol='owned-sitl',locator=identity['path'],ledger=str(root),
            scope='mission-vehicle:'+digest+':'+target,
            resources=[dict(name='vehicle.control',mode='exclusive',conflict_group='vehicle.control')])
        expected=dict(identity=identity,journal=str(journal.path),journal_inode=journal.path.stat().st_ino,target=target)
        with ProviderRegistry().transaction() as (data,store):
            old=next((b for b in data['bindings'] if b['ledger']==str(root)),None)
            if old is None:
                if root.exists():raise ValueError('unbound Mission vehicle state exists')
                ProviderRegistry.register(data,store,binding)  # commit unique identity BEFORE initializing its pointer
                root.mkdir(mode=0o700)
                DurableRecord(root/'journal.json').write(expected,create=True)
            elif old!=binding:raise ValueError('vehicle epoch/journal/target binding changed')
            if DurableRecord(root/'journal.json').read()!=expected:raise ValueError('Mission journal identity/pointer missing or inconsistent')
        result[target]=identity
    return result
