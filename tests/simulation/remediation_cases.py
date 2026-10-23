"""Review regressions on the owned real AP link; no direct vehicle sender."""
from dataclasses import replace
from datetime import timedelta
import time
from threading import Event, Thread

from vehicle_autonomy.contracts.core.primitives import SchemaVersion
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect, DisarmEffect, EffectEnvelope, ModeEffect


def later(point, ns):
    return replace(point,monotonic_ns=point.monotonic_ns+ns,
                   utc=point.utc+timedelta(microseconds=ns//1000))


def run(runtime, proxy, pump, writes):
    result={}
    runtime.begin_run(allow_send=True)
    def wait(name):
        until=time.monotonic()+8
        while time.monotonic()<until:
            pump(.1)
            status=runtime.effect_status(name)
            if status['phase']=='COMPLETED':return status
            if status['phase'] in ('UNKNOWN','REJECTED'):
                raise AssertionError(f'{name}: {status}')
        raise TimeoutError(f'{name}: {runtime.effect_status(name)}')
    def command(name,effect):
        admitted=runtime.submit_effect(effect,effect_id=name)
        if admitted.reason:raise AssertionError(admitted.reason)
        return wait(name)
    command('review-guided',ModeEffect('GUIDED'))
    with proxy._lock:
        previous=next(r for r in reversed(proxy.records) if r.get('direction')=='rx_forward'
                      and r.get('type')=='HEARTBEAT' and not r['payload']['base_mode'] & 128)
        old_heartbeat=bytes.fromhex(previous['raw_hex'])
    arm=command('review-arm',ArmEffect())
    with proxy._lock:
        old_ack=bytes.fromhex(next(r for r in reversed(proxy.records) if r.get('direction')=='rx_forward'
                    and r.get('type')=='COMMAND_ACK' and r['payload']['command']==400)['raw_hex'])
    before=len(writes)
    proxy.inject(hold_tx_commands={400})
    admitted=runtime.submit_effect(DisarmEffect(),effect_id='review-disarm')
    if admitted.reason:raise AssertionError(admitted.reason)
    pump(.2)
    if len(writes)!=before+1:raise AssertionError('one actual Disarm write required')
    with proxy._lock:
        if len(proxy._held_tx)!=1:raise AssertionError('real Disarm was not held')
    proxy.replay_rx(old_ack)
    proxy.replay_rx(old_heartbeat)
    pump(.4)
    status=runtime.effect_status('review-disarm')
    state=runtime.world_snapshot().vehicle
    with proxy._lock:
        upstream_hb=next(dict(r) for r in reversed(proxy.records) if r.get('direction')=='rx' and r.get('type')=='HEARTBEAT')
    if (status['phase']=='COMPLETED' or not state.operation.armed or len(writes)!=before+1
            or not upstream_hb['payload']['base_mode'] & 128):
        raise AssertionError(f'old frames falsely completed Disarm: {status}')
    result['old_ack_heartbeat_replay']={'passed':True,'old_ack_hex':old_ack.hex(),
        'old_heartbeat_hex':old_heartbeat.hex(),'before_release':status,
        'last_qualified_state_armed':state.operation.armed,'last_real_upstream_heartbeat':upstream_hb,
        'writer_calls':len(writes)-before,
        'receive_rejections':dict(runtime._session.receive_rejections)}
    proxy.inject(hold_tx_commands=set())
    released_at=time.monotonic_ns()
    proxy.release_tx()
    disarm=wait('review-disarm')
    with proxy._lock:
        actual_new_acks=[dict(r) for r in proxy.records if r.get('direction')=='rx'
            and r.get('type')=='COMMAND_ACK' and r['payload']['command']==400 and r['host_ns']>=released_at]
    if not actual_new_acks:raise AssertionError('real AP Disarm ACK after held-frame release missing')
    result['old_ack_heartbeat_replay']['real_new_ack_after_release']=actual_new_acks[-1]
    if runtime.world_snapshot().vehicle.operation.armed:raise AssertionError('Disarm state not confirmed')
    # Legitimate consecutive use of command 400 must continue working.
    arm2=command('review-arm-2',ArmEffect())
    disarm2=command('review-disarm-2',DisarmEffect())
    result['normal_continuous_arm_disarm']={'passed':True,'statuses':[arm,disarm,arm2,disarm2],
                                          'final_armed':False}

    def short_request(name):
        now=runtime.clock()
        envelope=EffectEnvelope(SchemaVersion(1,0),name,runtime._run_id,runtime._action_id,
                                now,later(now,20_000_000),ModeEffect('GUIDED'))
        admitted=runtime.dispatch_envelope(envelope)
        if admitted.reason:raise AssertionError(f'{name}: {admitted.reason}')
        return envelope
    # Actual host monotonic expiration while queued behind the authority lock.
    before=len(writes);lock_request=short_request('review-lock-expiry')
    entered=Event();finished=Event();errors=[];stale_now=runtime.clock();lock_trace={}
    if stale_now.monotonic_ns>=lock_request.deadline.monotonic_ns:
        raise AssertionError('lock-expiry fixture already expired before scheduling')
    def worker():
        lock_trace['attempted_at_ns']=runtime.clock().monotonic_ns
        entered.set()
        try:runtime._port.write_next(stale_now)
        except BaseException as exc:errors.append(str(exc))
        finally:finished.set()
    with runtime.authority.lock:
        thread=Thread(target=worker);thread.start()
        if not entered.wait(1):raise AssertionError('writer thread not started')
        if lock_trace['attempted_at_ns']>=lock_request.deadline.monotonic_ns:
            raise AssertionError('lock-expiry fixture started after expiry')
        time.sleep(.03)
        lock_trace['released_at_ns']=runtime.clock().monotonic_ns
    if not finished.wait(1):raise AssertionError('writer thread stuck')
    thread.join()
    status=runtime.effect_status('review-lock-expiry')
    if errors or len(writes)!=before or status['phase']!='REJECTED' or status['reason']!='expired':
        raise AssertionError(f'lock expiry wrote: {status}, {errors}')
    result['lock_expiry']={'passed':True,'status':status,'writer_calls':0,'wait_s':.03,'request_ttl_s':.02,
        'deadline_ns':lock_request.deadline.monotonic_ns,'trace':lock_trace}
    pump(.1)

    original=runtime._port._write_guard
    guard_trace={}
    def slow_guard(command):
        guard_trace['started_at_ns']=runtime.clock().monotonic_ns
        approval=original(command)
        time.sleep(.03)
        guard_trace['finished_at_ns']=runtime.clock().monotonic_ns
        return approval
    before=len(writes);guard_request=short_request('review-guard-expiry')
    runtime._port._write_guard=slow_guard
    try:
        # Schedule the prepared Execution request directly at the sole writer;
        # a preceding socket read must not expire it before Guard even starts.
        runtime._port.write_next(runtime.clock())
    finally:
        runtime._port._write_guard=original
    if not (guard_trace.get('started_at_ns',2**64)<guard_request.deadline.monotonic_ns
            <=guard_trace.get('finished_at_ns',0)):
        raise AssertionError(f'Guard did not actually straddle deadline: {guard_trace}')
    status=runtime.effect_status('review-guard-expiry')
    if len(writes)!=before or status['phase']!='REJECTED' or status['reason'] not in ('expired','write_guard_timeout'):
        raise AssertionError(f'guard expiry wrote: {status}')
    result['guard_expiry']={'passed':True,'status':status,'writer_calls':0,'guard_s':.03,'request_ttl_s':.02,
        'deadline_ns':guard_request.deadline.monotonic_ns,'trace':guard_trace}
    result['valid_after_rejections']={'passed':True,'status':command('review-fresh',ModeEffect('GUIDED'))}
    # Every attempted wire frame is independently decoded, including across wraps.
    frames=[proxy.frame_metadata(bytes.fromhex(w['raw_hex'])) for w in writes]
    sequences=[frame['sequence'] for frame in frames]
    if any(b!=(a+1)&255 for a,b in zip(sequences,sequences[1:])):
        raise AssertionError(f'wire sequence differs from writer order: {sequences}')
    result['wire_order']={'passed':True,'sequences':sequences,'frames':frames}
    runtime.end_run()
    return result
