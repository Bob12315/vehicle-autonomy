"""Bind each real owned SITL epoch to one Mission journal and target label.

Uses Phase 3's fixed trusted local ProviderRegistry. An empty second journal,
an alias or a changed data-dir cannot discard that vehicle's uncertain history.
"""
import hashlib
from pathlib import Path

from vehicle_autonomy.engine.action.durable import DurableRecord, canonical
from vehicle_autonomy.engine.action.provider_identity import ProviderRegistry
from vehicle_autonomy.app.bootstrap.mission_recovery import deployment_identity


def live_instance(service, target):
    """A coherent, read-only execution identity, never a selector default.

    Retired Drivers remain available for historical command evidence, but are
    never execution candidates. Call while holding the application's ingress lock.
    """
    if type(target) is not str or target not in service.drivers or target in getattr(service, '_retired_simulation_targets', set()):
        raise ValueError('selected vehicle instance removed or unknown')
    manager = getattr(service, 'simulation_manager', None)
    if manager and target in manager.retiring_targets():
        raise ValueError('selected vehicle instance is retiring')
    driver = service.drivers[target]
    info, world = driver.read_view() if callable(getattr(driver, 'read_view', None)) else (driver.info(), driver.snapshot())
    if not info.get('connected') or not info.get('session_id') or world is None:
        raise ValueError('selected vehicle instance offline')
    state = world.vehicle
    if state is None or state.health.quality.value != 'VALID':
        raise ValueError('selected vehicle state unavailable or invalid')
    try:
        fresh = all(0 <= service.clock().elapsed_ns_since(stamp) <= 3_000_000_000
                    for stamp in (world.published_at, state.published_at))
    except ValueError:
        fresh = False
    if not fresh:
        raise ValueError('selected vehicle instance stale')
    metadata = getattr(service, '_simulation_instances', {}).get(target, {})
    identity = service.deployment_identities.get(target)
    telemetry = state.telemetry
    system = None if telemetry is None else telemetry.source_system
    if metadata and system != metadata['system_id']:
        raise ValueError('vehicle System ID differs from owned instance')
    return dict(target=target, kind=driver.context().target_kind,
                vehicle_id=metadata.get('vehicle_id', str(state.vehicle_id)),
                system_id=system, world=metadata.get('world', (identity or {}).get('world')),
                simulation_session=metadata.get('simulation_session'),
                epoch=None if identity is None else hashlib.sha256(canonical(identity)).hexdigest(),
                session_id=info['session_id'], generation=str(world.version.generation_id))


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
