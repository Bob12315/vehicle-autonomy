"""Real proxy regressions on a stationary, owned signed Plane before takeoff."""
from dataclasses import replace
from threading import Event, Thread
import time
from vehicle_autonomy.app.bootstrap.simulation_runtime import _later
from vehicle_autonomy.contracts.core.primitives import SchemaVersion
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect, DisarmEffect, EffectEnvelope, ModeEffect


def _wrap_replay_evidence(runtime, proxy, cycle, old_ack, old_hbs, writes, before):
    with proxy._lock:cursor=len(proxy.records)
    wraps=0;last=None;end=time.monotonic()+20;initial=runtime._receive_signing.rejected['replay']
    # Three packet wraps can precede the unchanged command deadline. Continue
    # scheduling the Runtime until it has actually observed the timeout and
    # consumed the injected frames; packet rate is not a command timer.
    while time.monotonic()<end:
        cycle()
        with proxy._lock:batch=list(proxy.records[cursor:]);cursor=len(proxy.records)
        for r in batch:
            if r.get('direction')!='rx':continue
            seq=r['sequence']
            if wraps<3 and last is not None and seq<last:
                wraps+=1;proxy.replay_rx(old_ack)
                for raw in old_hbs:proxy.replay_rx(raw)
            last=seq
        status=runtime.effect_status('plane-wrap-disarm')
        if status['phase']=='COMPLETED' or not runtime.world_snapshot().vehicle.operation.armed:
            raise AssertionError('old ACK/HEARTBEAT changed command or World')
        if (wraps==3 and status['phase']=='UNKNOWN'
                and runtime._receive_signing.rejected['replay']-initial>=wraps*3):
            break
    status=runtime.effect_status('plane-wrap-disarm')
    if (wraps<3 or status['phase']!='UNKNOWN' or len(writes)!=before+1
            or runtime._receive_signing.rejected['replay']-initial<wraps*3
            or runtime._effects['plane-wrap-disarm'] in runtime._port.ack_evidence):
        raise AssertionError('replay/timeout evidence incomplete')
    return dict(passed=True,wraps=wraps,status=status,world_armed=True,
        old_ack_accepted=False,writer_calls=1,replay_rejections=runtime._receive_signing.rejected['replay']-initial)


def ground(runtime,proxy,cycle,command,writes):
    result={}
    def short(name):
        now=runtime.clock()
        envelope=EffectEnvelope(SchemaVersion(1,0),name,runtime._run_id,runtime._action_id,
            now,_later(now,20_000_000),ModeEffect('MANUAL'))
        admitted=runtime.dispatch_envelope(envelope)
        if admitted.reason:raise AssertionError(admitted.reason)
        return envelope
    before=len(writes);short('plane-lock-expiry');entered=Event();done=Event();errors=[]
    def writer():
        entered.set()
        try:runtime._port.write_next(runtime.clock())
        except BaseException as exc:errors.append(type(exc).__name__)
        finally:done.set()
    with runtime.authority.lock:
        worker=Thread(target=writer);worker.start()
        if not entered.wait(1):raise AssertionError('writer not scheduled')
        time.sleep(.03)
    if not done.wait(1):raise AssertionError('writer stuck')
    worker.join()
    if errors or len(writes)!=before:raise AssertionError('expired lock wait wrote bytes')
    result['lock_expiry']=dict(passed=True,writer_calls=0,status=runtime.effect_status('plane-lock-expiry'))
    cycle()
    before=len(writes);short('plane-guard-expiry');original=runtime._port._write_guard
    def slow(envelope):
        time.sleep(.03);return original(envelope)
    runtime._port._write_guard=slow
    try:runtime._port.write_next(runtime.clock())
    finally:runtime._port._write_guard=original
    if len(writes)!=before:raise AssertionError('expired guard wrote bytes')
    result['guard_expiry']=dict(passed=True,writer_calls=0,status=runtime.effect_status('plane-guard-expiry'))
    cycle()
    lease=runtime.authority.lease
    runtime.authority.grant(replace(lease,expires_at=_later(runtime.clock(),20_000_000)),runtime.clock())
    runtime.authority.set_action_send(True)
    before=len(writes);short('plane-lease-expiry');time.sleep(.03);runtime._port.write_next(runtime.clock())
    if len(writes)!=before:raise AssertionError('expired lease wrote bytes')
    result['lease_expiry']=dict(passed=True,writer_calls=0,status=runtime.effect_status('plane-lease-expiry'))
    runtime.authority.grant(lease,runtime.clock());runtime.authority.set_action_send(True)
    cycle()
    result['valid_after_rejections']=dict(passed=True,status=command('plane-fresh-manual',ModeEffect('MANUAL')))
    with proxy._lock:
        old_hbs=[bytes.fromhex(r['raw_hex']) for r in proxy.records if r.get('direction')=='rx_forward'
            and r.get('type')=='HEARTBEAT' and not r['payload']['base_mode'] & 128][-2:]
    if len(old_hbs)!=2:raise AssertionError('two actual old unarmed heartbeats required')
    command('plane-replay-arm',ArmEffect())
    with proxy._lock:
        old_ack=bytes.fromhex(next(r for r in reversed(proxy.records) if r.get('direction')=='rx_forward'
            and r.get('type')=='COMMAND_ACK' and r['payload']['command']==400)['raw_hex'])
    before=len(writes);proxy.inject(hold_tx_commands={400})
    admitted=runtime.submit_effect(DisarmEffect(),effect_id='plane-wrap-disarm')
    if admitted.reason:raise AssertionError(admitted.reason)
    cycle()
    if len(writes)!=before+1:raise AssertionError('one valid Disarm write required')
    result['wrap_replay']=_wrap_replay_evidence(runtime,proxy,cycle,old_ack,old_hbs,writes,before)
    old_session=runtime.session_id
    runtime._close_link('plane_review_epoch_end');proxy.disconnect();time.sleep(.15)
    proxy.inject(hold_tx_commands=set());runtime.connect()
    end=time.monotonic()+1.5
    while time.monotonic()<end:cycle()
    if runtime.session_id==old_session or runtime.authority.system_send or runtime.authority.lease:
        raise AssertionError('reconnect retained old authorization')
    runtime.begin_run(allow_send=True)
    command('plane-new-disarm',DisarmEffect())
    statuses=[]
    for i in range(2):
        statuses.append(command(f'plane-normal-arm-{i}',ArmEffect()))
        statuses.append(command(f'plane-normal-disarm-{i}',DisarmEffect()))
    result['normal_arm_disarm']=dict(passed=True,statuses=statuses,world_armed=runtime.world_snapshot().vehicle.operation.armed)
    return result
