"""Transient browser ingress reservation, never a vehicle execution authority.

The real Action resources, SEND gates, execution lease and stop barriers remain
authoritative. Losing a browser reservation requests the same Runtime exits.
"""
import secrets
import time

from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.engine.mission.graph_runtime import TERMINAL


class OperatorControls:
    def __init__(self, service, *, clock=time.monotonic, ttl_s=10):
        self.service=service;self.clock=clock;self.ttl_s=ttl_s;self.records={};self.owners={};self.auth_stores={}

    def vehicle(self, target):
        driver=self.service.drivers[target]
        info,world=driver.read_view() if callable(getattr(driver,'read_view',None)) else (driver.info(),driver.snapshot())
        fresh=False
        if world and world.vehicle:
            try:fresh=bool(info.get('connected') and world.vehicle.health.quality.value=='VALID' and 0<=self.service.clock().elapsed_ns_since(world.vehicle.published_at)<=3_000_000_000)
            except ValueError:pass
        generation=None if world is None else str(world.version.generation_id)
        return info,world,fresh,generation

    def safe(self, action):
        return action['state']=='REJECTED' or bool(action['state'] in TERMINAL and action['safety'] and action['safety']['release_safe'])

    def request_exit(self, record):
        if record['releasing']:return
        record['releasing']=True
        for identifier in tuple(record['actions']):
            a=self.service.runtime.view(identifier)
            if not self.safe(a):self.service.runtime.cancel(identifier)

    def tick(self):
        for identifier,principal in tuple(self.owners.items()):
            store=self.auth_stores.get(principal)
            if store and not store.alive(principal):
                action=self.service.runtime.view(identifier)
                if action['kind']!='Query' and not self.safe(action):self.service.runtime.cancel(identifier)
                self.owners.pop(identifier,None)
        for target,r in tuple(self.records.items()):
            info,world,fresh,generation=self.vehicle(target)
            epoch_changed=info.get('session_id')!=r['epoch'] or generation!=r['generation']
            if epoch_changed:
                # The existing Plane driver intentionally opens a new read-only
                # link during a successful, explicit flight continuation.
                a=next((self.service.runtime.view(i) for i in r['actions'] if i==info.get('scope')),None)
                if a and a.get('continuation_of') in r['actions']:
                    r.update(epoch=info.get('session_id'),generation=generation)
                elif not (info.get('connected') and any(
                    self.service.runtime.view(i).get('continuation_of') in r['actions'] and
                    self.service.runtime.view(i)['state'] not in TERMINAL for i in r['actions'])):
                    self.request_exit(r)
            if self.clock()>=r['expires'] or not r['sessions'].alive(r['principal']) or not info.get('connected'):self.request_exit(r)
            if r['releasing'] and all(self.safe(self.service.runtime.view(i)) for i in r['actions']):self.records.pop(target,None)

    def acquire(self, target, principal, sessions):
        self.tick();self.service._require_operational()
        if target in self.records:raise ValueError('target is reserved; release or explicitly request takeover')
        info,world,fresh,generation=self.vehicle(target)
        if not info.get('owned_simulation') or not info.get('deployment_send'):raise ValueError('only explicitly authorized owned simulation is controllable; hardware remains read-only')
        if not fresh:raise ValueError('fresh valid vehicle telemetry required')
        self.service._idle(target)
        token=secrets.token_urlsafe(32)
        self.records[target]=dict(token=token,principal=principal,sessions=sessions,expires=self.clock()+self.ttl_s,
            epoch=info.get('session_id'),generation=generation,actions=set(),releasing=False)
        return dict(control_token=token,ttl_s=self.ttl_s,state='MANUAL_CONTROL',target=target)

    def check(self, target, principal, token, *, fresh=False):
        self.tick();r=self.records.get(target)
        if not r or r['releasing'] or r['principal']!=principal or not secrets.compare_digest(r['token'],token):raise ValueError('Acquire Control is required; control lost, expired or held by another page')
        if fresh and not self.vehicle(target)[2]:raise ValueError('telemetry stale; command blocked')
        return r

    def renew(self, target, principal, token):
        r=self.check(target,principal,token);r['expires']=self.clock()+self.ttl_s
        return dict(state='MANUAL_CONTROL',ttl_s=self.ttl_s)

    def release(self, target, principal, token):
        r=self.check(target,principal,token);self.request_exit(r);self.tick()
        return dict(state='RELEASING' if target in self.records else 'OBSERVER',physical_exit_confirmed=target not in self.records)

    def logout(self, principal):
        for r in self.records.values():
            if r['principal']==principal:self.request_exit(r)
        for identifier,owner in tuple(self.owners.items()):
            if owner==principal:
                a=self.service.runtime.view(identifier)
                if a['kind']!='Query' and not self.safe(a):self.service.runtime.cancel(identifier)

    def snapshot(self, principal, token):
        self.tick();result={}
        for target in self.service.drivers:
            r=self.records.get(target);info,world,fresh,generation=self.vehicle(target)
            mine=bool(r and r['principal']==principal and secrets.compare_digest(r['token'],token))
            try:self.service._idle(target);idle=True;reason=''
            except ValueError as exc:idle=False;reason=str(exc)
            eligible=bool(info.get('owned_simulation') and info.get('deployment_send') and fresh and idle and not r)
            result[target]=dict(state='RELEASING' if r and r['releasing'] else 'MANUAL_CONTROL' if mine else 'OBSERVER',
                mine=mine,holder='当前控制页面' if mine else '其他控制页面' if r else 'Mission / Action' if not idle else None,
                can_acquire=eligible,reason='控制页面已预留' if r and not mine else reason if not idle else '遥测过期或未知' if not fresh else '仅限授权的自有仿真' if not info.get('deployment_send') or not info.get('owned_simulation') else '',
                expires_in_s=max(0,r['expires']-self.clock()) if r else None,
                system_send=info.get('system_send'),action_send=info.get('action_send'),execution_scope=info.get('scope'),
                preflight=dict(telemetry_valid=fresh,owned_simulation=info.get('owned_simulation') is True,deployment_send=info.get('deployment_send') is True,
                    runtime_healthy=self.service.control_fault is None,physical_scope_free=idle))
        return result
