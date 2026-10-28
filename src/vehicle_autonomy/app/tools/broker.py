"""Authenticated Agent registry/mailbox, independent of the vehicle scheduler."""
from copy import deepcopy
import hmac
import json
from threading import RLock
import time
from uuid import uuid4

from vehicle_autonomy.app.web.server import ConsoleServer, Handler
from .schema import context, identifier, number, object_fields, string, tool_report


class AgentRegistry:
    def __init__(self, store, *, clock=time.monotonic, heartbeat_timeout_s=5):
        self.store = store; self.clock = clock; self.timeout = heartbeat_timeout_s
        self.lock = RLock(); self.agents = {}; self.jobs = {}; self.epoch = uuid4().hex

    def online(self, agent):
        return 0 <= self.clock() - agent['seen'] < self.timeout

    def exchange(self, agent_id, payload):
        object_fields(payload, ('boot_id', 'sequence', 'name', 'role', 'tools', 'results'))
        identifier(agent_id); identifier(payload['boot_id']); string(payload['name'], 128)
        if payload['role'] not in ('desktop', 'server', 'onboard'): raise ValueError('invalid Agent role')
        seq = payload['sequence']
        if type(seq) is not int or not 0 <= seq <= 2**53: raise ValueError('invalid heartbeat sequence')
        if type(payload['tools']) is not list or len(payload['tools']) > 48: raise ValueError('bounded Tool snapshot required')
        ids = set()
        for tool in payload['tools']:
            tool_report(tool)
            if tool['manifest']['id'] in ids: raise ValueError('duplicate Tool report')
            ids.add(tool['manifest']['id'])
        if type(payload['results']) is not list or len(payload['results']) > 128: raise ValueError('bounded command results required')
        for result in payload['results']:
            object_fields(result,('id','ok','result','error'));identifier(result['id'])
            if type(result['ok']) is not bool or result['result'] is not None and type(result['result']) is not dict:raise ValueError('invalid Tool result')
            if result['error'] is not None and (type(result['error']) is not str or len(result['error'])>1024):raise ValueError('bounded result error required')
        with self.lock:
            old = self.agents.get(agent_id)
            if old:
                if payload['boot_id'] in old['retired']: raise ValueError('retired Agent boot')
                if old['boot_id'] == payload['boot_id'] and seq <= old['sequence']: raise ValueError('replayed heartbeat')
                if old['boot_id'] != payload['boot_id'] and self.online(old): raise ValueError('Agent identity already active')
            elif len(self.agents) >= 32: raise ValueError('Agent budget exhausted')
            retired = [] if old is None else list(old['retired'])
            if old and old['boot_id'] != payload['boot_id']:
                if len(retired) >= 128: raise ValueError('Agent boot budget exhausted; rotate identity')
                retired.append(old['boot_id'])
            self.store.audit('agent.heartbeat' if old and old['boot_id'] == payload['boot_id'] else 'agent.register',
                             agent=agent_id, boot_id=payload['boot_id'], sequence=seq)
            value = deepcopy(payload)
            value.update(id=agent_id, seen=self.clock(), retired=retired)
            self.agents[agent_id] = value
            acknowledged = []
            for result in payload['results']:
                job = self.jobs.get(result['id'])
                if job is None:
                    # Backend restart does not replay old jobs. Acknowledge the
                    # transport record so old unrecognized results cannot fill
                    # the Agent outbox and starve fresh command results.
                    acknowledged.append(result['id']);continue
                if job and job['agent_id'] == agent_id and job['boot_id'] == payload['boot_id']:
                    if job['state'] in ('DELIVERED', 'UNKNOWN'):
                        job.update(state='SUCCEEDED' if result['ok'] else 'FAILED', result=deepcopy(result['result']), error=result['error'])
                        self.store.audit('tool.result', job=job['id'], state=job['state'], agent=agent_id)
                    acknowledged.append(result['id'])
            commands = []
            for job in self.jobs.values():
                if job['agent_id'] != agent_id or job['boot_id'] != payload['boot_id']: continue
                remaining = job['deadline'] - self.clock()
                if remaining <= 0:
                    if job['state'] == 'QUEUED': job.update(state='EXPIRED', error='command expired before delivery')
                    elif job['state'] == 'DELIVERED': job.update(state='UNKNOWN', error='Agent command result unconfirmed')
                elif job['state'] in ('QUEUED', 'DELIVERED') and len(commands) < 16:
                    job['state'] = 'DELIVERED'
                    commands.append({k:deepcopy(job[k]) for k in ('id', 'boot_id', 'operation', 'tool_id', 'profile_id', 'context')} | dict(expires_in_s=remaining))
            return dict(server_epoch=self.epoch, boot_id=payload['boot_id'], sequence=seq, commands=commands, acknowledged=acknowledged)

    def submit(self, agent_id, operation, tool_id, profile_id, ctx):
        identifier(agent_id); identifier(tool_id); identifier(profile_id); ctx = context(ctx)
        if operation not in ('launch', 'stop', 'restart', 'check', 'connect', 'open'): raise ValueError('unsupported tool operation')
        with self.lock:
            agent = self.agents[agent_id]
            if not self.online(agent): raise ValueError('Agent disconnected')
            tool = next(t for t in agent['tools'] if t['manifest']['id'] == tool_id)
            if profile_id not in tool['manifest']['profiles']: raise ValueError('unknown registered profile')
            if len(self.jobs) >= 4096: raise ValueError('command budget exhausted; re-admit backend')
            job = dict(id=uuid4().hex, agent_id=agent_id, boot_id=agent['boot_id'], operation=operation,
                       tool_id=tool_id, profile_id=profile_id, context=ctx,
                       deadline=self.clock() + 10, state='QUEUED', result=None, error=None)
            self.store.audit('tool.request', job=job['id'], agent=agent_id, operation_name=operation, tool=tool_id)
            self.jobs[job['id']] = job
            return deepcopy(job)

    def snapshot(self):
        with self.lock:
            agents = []
            for agent in self.agents.values():
                value = {k:deepcopy(v) for k, v in agent.items() if k not in ('results', 'retired', 'seen')}
                value.update(connected=self.online(agent), heartbeat_age_s=max(0, self.clock() - agent['seen']))
                if not value['connected']:
                    for tool in value['tools']:
                        if tool['instance']:
                            tool['instance'].update(state='DISCONNECTED', process_running=None, ready=False, service_health='UNKNOWN', connection='DISCONNECTED')
                agents.append(value)
            for job in self.jobs.values():
                if job['state'] in ('QUEUED', 'DELIVERED') and self.clock() >= job['deadline']:
                    job.update(state='EXPIRED' if job['state'] == 'QUEUED' else 'UNKNOWN', error='command deadline elapsed')
            return dict(agents=agents, jobs=deepcopy(list(self.jobs.values())[-128:]), server_epoch=self.epoch)


class AgentServer(ConsoleServer):
    def __init__(self, address, registry, credentials, audit_path):
        if not credentials or len(credentials) > 32: raise ValueError('1..32 allowlisted Agent credentials required')
        for key, token in credentials.items():
            identifier(key)
            if type(token) is not str or not 32 <= len(token) <= 256: raise ValueError('strong Agent token required')
        if len(set(credentials.values()))!=len(credentials):raise ValueError('each Agent requires a distinct credential')
        self.credentials = dict(credentials)
        super().__init__(address, registry, '', audit_path)
        self.RequestHandlerClass = AgentHandler


class AgentHandler(Handler):
    def do_GET(self): self.reply(404, dict(ok=False, error='Agent exchange requires POST'))

    def do_POST(self):
        agent_id = self.headers.get('X-VAF-Agent', '')
        supplied = self.headers.get('Authorization', '')
        token = self.server.credentials.get(agent_id)
        port = self.server.server_address[1]
        if (self.path != '/v1/exchange' or self.headers.get('Origin') is not None or
            self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}')):
            self.reply(403, dict(ok=False, error='invalid Agent channel')); return
        if token is None or not hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
            self.server.audit.info(json.dumps(dict(operation='agent.authentication', ok=False)))
            self.reply(401, dict(ok=False, error='Agent authentication required')); return
        try:
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type') != 'application/json': raise ValueError('bounded JSON required')
            length = int(self.headers.get('Content-Length', '-1'))
            if not 0 <= length <= 1_500_000: raise ValueError('Agent snapshot too large')
            payload = json.loads(self.rfile.read(length), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('finite JSON required')))
            result = self.server.service.exchange(agent_id, payload)
            self.reply(200, dict(ok=True, result=result))
        except Exception as exc:
            self.reply(409, dict(ok=False, error=type(exc).__name__ + ': ' + str(exc)[:400]))
