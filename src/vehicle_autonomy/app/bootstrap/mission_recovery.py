"""Read-only reconstruction for this application's explicitly owned simulations.

Never grants SEND or resumes an Action. External jobs still need their existing
ProviderRegistry reconciliation; a vehicle observation cannot discharge them.
"""
import json
from pathlib import Path


def deployment_identity(driver):
    proof = getattr(driver, 'ownership', None)
    if proof is None: return None
    proof.assert_alive()
    return dict(path=str(proof.path), directory=list(proof.identity), world=proof.world, model=proof.model,
        kind=proof.kind, processes=[dict(name=p['name'],pid=p['pid'],start_ticks=p['start_ticks']) for p in proof.processes])


def retired_simulation(identity):
    if not isinstance(identity, dict): return False
    try:
        path = Path(identity['path'])
        info = path.parent.stat()
        if [info.st_dev,info.st_ino] != identity['directory'] or path.resolve() != path or path.stat().st_size > 1048576:
            return False
        manifest = json.loads(path.read_text())
        if (not manifest.get('ended_at') or not manifest.get('credentials_removed') or not manifest.get('ports_released')
                or manifest.get('remaining_process_groups') != [] or manifest.get('world') != identity['world']
                or manifest.get('model') != identity['model']): return False
        for p in identity['processes']:
            if not any(m['name']==p['name'] and m['pid']==p['pid'] and m['start_ticks']==p['start_ticks'] for m in manifest['processes']):
                return False
            try:
                stat=(Path('/proc')/str(p['pid'])/'stat').read_text().rsplit(')',1)[1].split()
                if stat[0] != 'Z' and stat[19] == str(p['start_ticks']): return False
            except FileNotFoundError: pass
        return {p['name'] for p in identity['processes']} == {'sitl','gazebo'}
    except (OSError,ValueError,KeyError,TypeError): return False


def reconstruct(driver, identities, now):
    current = deployment_identity(driver)
    if current is None: raise ValueError('explicit owned simulation identity required')
    if any(old is None or old != current and not retired_simulation(old) for old in identities):
        raise ValueError('old simulation identity is unresolved; new alias/fixture is not proof of its exit')
    info = driver.info()
    proof = driver.ownership
    if (not info.get('connected') or info.get('scope') or info.get('system_send') or info.get('action_send')
            or info.get('lease_active') or proof.receive_signing.accepted == 0):
        raise ValueError('read-only authenticated reconstruction required')
    world = driver.snapshot()
    if world is None or world.vehicle is None: raise ValueError('fresh vehicle unavailable')
    state = world.vehicle
    if (state.health.quality.value != 'VALID' or state.operation.armed is not False or
            state.reported_pose is None or state.reported_twist is None or
            str(state.reported_pose.frame_id) != 'odom' or str(state.reported_twist.frame_id) != 'odom'):
        raise ValueError('trusted disarmed odom state required')
    for stamp in (state.published_at,state.reported_pose.captured_at,state.reported_twist.captured_at):
        if not 0 <= now.elapsed_ns_since(stamp) <= 3_000_000_000: raise ValueError('reconstruction state stale/future')
    p,t = state.reported_pose.value.position,state.reported_twist.value
    if abs(p.z) > .25 or sum(v*v for v in (t.linear.x,t.linear.y,t.linear.z)) > .1**2 or abs(t.angular.z) > .15:
        raise ValueError('confirmed stationary ground required; airborne recovery is not ordinary takeover')
    return dict(snapshot_id=str(world.snapshot_id),session_id=info['session_id'],
        disarmed_stationary_ground=True,owned_identity=current,old_outcome='UNKNOWN',new_send_required=True)
