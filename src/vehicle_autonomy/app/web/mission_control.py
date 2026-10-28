"""Mission Studio/Manual use cases sharing the existing Action Lab scheduler."""
from collections import deque
from copy import deepcopy
from pathlib import Path
import re
from urllib.parse import urlsplit,parse_qs
from threading import RLock
from uuid import uuid4

from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.app.bootstrap.mission_recovery import deployment_identity, reconstruct
from vehicle_autonomy.app.bootstrap.mission_binding import bind_simulations
from vehicle_autonomy.engine.mission.graph import NODE_TYPES
from vehicle_autonomy.engine.mission.graph_runtime import MissionGraphRuntime, TERMINAL
from vehicle_autonomy.engine.mission.journal import MissionJournal
from vehicle_autonomy.world.model.mission_inputs import LocalEvents
from vehicle_autonomy.app.web.action_lab import ActionLab, ActionLabHandler, ActionLabServer


class MissionControl(ActionLab):
    def __init__(self, drivers, data_dir, *, registry=None, event_sink=None, events=None, scheduler_period_s=.05):
        self._control_lock = RLock()
        self.missions = None
        self.manual = {}
        self.recovered_manual = {}
        self.manual_records = {}
        self.manual_bindings = {}
        self.deployment_identities = {}
        self._tracks = {}
        self.control_fault = None
        self.journal = None
        super().__init__(drivers, registry=registry, event_sink=event_sink,scheduler_period_s=scheduler_period_s)
        try:
            self.journal = MissionJournal(Path(data_dir) / 'missions')
            self.recovered_manual = deepcopy(self.journal.data['manual'])
            for identifier, record in self.recovered_manual.items():
                if record['state'] not in TERMINAL or not record.get('release_safe', False):
                    record.update(state='UNKNOWN', release_safe=False, continuation_allowed=False,
                        error='application restarted; no control or input session resumed')
                    self.journal.save_manual(identifier, record)
            self.deployment_identities = bind_simulations(self.drivers,self.journal)
            self.events = events or LocalEvents()
            self.missions = MissionGraphRuntime(self.runtime, self.journal, self.events, clock=self.clock,
                deployment_identities=self.deployment_identities,recovered_manual=self.recovered_manual)
        except BaseException:
            self._stop.set();self._thread.join(5)
            if self.journal:self.journal.close()
            # A failed assembly never closes a caller's already-owned Driver.
            raise

    def _fence_all(self):
        for a in self.runtime.views():
            if a['state'] not in TERMINAL or a['safety'] and a['safety']['continuation_allowed']:
                self.runtime.cancel(a['id'])

    def _run(self):
        while not self._stop.wait(self.scheduler_period_s):
            with self._control_lock:
                if self.missions is None: continue
                try:
                    # Durable intent precedes every callback that may emit.
                    if self.control_fault is None:
                        self.missions.tick()
                        self._sync_manual()
                    for session in tuple(self.manual.values()):
                        if self.drivers[session['target']].info().get('session_id') != session['vehicle_session']:
                            self.runtime.cancel(session['action_id'])
                except Exception as exc:
                    self.control_fault = 'control fenced: ' + type(exc).__name__
                if self.control_fault: self._fence_all()
                # A failed journal must never suppress independent exit cleanup.
                self.runtime.tick()
                if self.control_fault is None:
                    try: self._sync_manual()
                    except Exception as exc:
                        self.control_fault = 'control fenced: ' + type(exc).__name__
                        self._fence_all()

    def _sync_manual(self):
        for identifier, action_id in self.manual_records.items():
            a = self.runtime.journal_view(action_id)
            safe = a['state'] == 'REJECTED' or bool(a['safety'] and a['safety']['release_safe'])
            record = dict(provider_binding=deepcopy(self.manual_bindings.get(action_id)),version=a['version'],resource_claims=to_json_value(self.registry.resolve_typed(a['name'],a['version']).spec.resources),deployment_identity=deepcopy(self.deployment_identities.get(a['target'])), id=action_id, target=a['target'], name=a['name'], parameters=a['parameters'],
                state=a['state'], release_safe=safe, continuation_allowed=bool(a['safety'] and a['safety']['continuation_allowed']),
                safety=a['safety'], error=a['error'], deadline_ns=a['deadline_ns'], input_sequence=a['input_sequence'],
                history=a['history'][-16:], command_results=a['command_results'][-8:])
            if self.journal.data['manual'].get(identifier) != record: self.journal.save_manual(identifier, record)

    def _require_operational(self):
        if self.control_fault: raise ValueError(self.control_fault)

    def _idle(self, target, continuation=None):
        for a in self.recovered_manual.values():
            if a['target'] == target and not a['release_safe']:
                raise ValueError('restarted manual control remains UNKNOWN; trusted reconstruction required')
        for m in self.missions.views():
            if m['target'] != target: continue
            if m['state'] not in TERMINAL or not m['release_safe']:
                if m['continuation_allowed'] and continuation == m['continuation_of']: continue
                raise ValueError('Mission owns target or has unresolved effects')
        for a in self.runtime.views():
            if a['target'] != target or a['kind'] == 'Query': continue
            safe = a['state'] == 'REJECTED' or bool(a['safety'] and a['safety']['release_safe'])
            if safe: continue
            if (a['state'] == 'SUCCEEDED' and a['safety'] and a['safety']['continuation_allowed']
                    and continuation == a['id']): continue
            raise ValueError('Action owns target or physical exit remains UNKNOWN')

    def _manual_action(self, p, *, continuous=False):
        allowed = {'name', 'target', 'parameters', 'version', 'allow_send', 'timeout_s', 'continuation_of'}
        if p.keys() - allowed: raise ValueError('unknown manual request fields')
        self._require_operational()
        target = p['target']
        spec = self.registry.resolve_typed(p['name'], p.get('version')).spec
        if not continuous and p['name'] in ('Drive','Turn','SetVelocity'):
            raise ValueError('manual motion requires a managed input session')
        if spec.kind.value != 'Query': self._idle(target, p.get('continuation_of'))
        if continuous:
            kind = self.drivers[target].context().target_kind
            if (kind, p['name']) not in (('rover', 'Drive'), ('copter', 'SetVelocity')):
                raise ValueError('managed manual input only supports audited Rover/Copter streams')
            if p.get('allow_send') is not True: raise ValueError('explicit manual SEND required')
            if len(self.manual) >= 256: raise ValueError('manual session budget exhausted')
            if not self.drivers[target].info().get('connected') or not self.drivers[target].info().get('session_id'): raise ValueError('connected vehicle session required')
        request = dict(p)
        if continuous: request['input_timeout_s'] = .4
        store=getattr(self.registry.resolve_typed(p['name'],p.get('version')).factory,'resource_store',None) or getattr(self.drivers[target],'resource_store',None)
        binding=None if store is None or spec.kind.value=='Query' else store.binding()
        intent = 'manual-intent:' + uuid4().hex
        if spec.kind.value != 'Query':
            self.journal.save_manual(intent, dict(id=None, target=target, name=p['name'],
                provider_binding=binding,version=spec.version,resource_claims=to_json_value(spec.resources),state='SUBMITTING', release_safe=False, continuation_allowed=False, error=None,
                deployment_identity=deepcopy(self.deployment_identities.get(target))))
        a = self.runtime.submit(**request)
        if spec.kind.value != 'Query':
            self.manual_records[intent] = a['id'];self.manual_bindings[a['id']]=binding
            try: self._sync_manual()
            except BaseException:
                self.runtime.cancel(a['id']);self.control_fault = 'manual intent persistence failed';raise
        if continuous:
            identifier = 'manual:' + uuid4().hex
            self.manual[identifier] = dict(id=identifier, target=target, action_id=a['id'],
                vehicle_session=self.drivers[target].info().get('session_id'), last_input_ns=None)
            return dict(session=self.manual[identifier].copy(), action=a)
        return a

    def _snapshot(self):
        vehicles = []
        for target, d in self.drivers.items():
            read=getattr(d,'read_view',None)
            info,world=read() if callable(read) else (d.info(),d.snapshot())
            track = self._tracks.setdefault(target, deque(maxlen=240))
            epoch = None if world is None else str(info.get('session_id'))
            state = None if world is None else world.vehicle
            if state and state.reported_pose:
                sample = dict(epoch=epoch, at_ns=state.reported_pose.captured_at.monotonic_ns,
                    frame=str(state.reported_pose.frame_id), position=to_json_value(state.reported_pose.value.position),
                    global_position=None if state.global_position is None else to_json_value(state.global_position))
                if track and track[-1]['epoch'] != epoch: track.clear()
                if not track or track[-1]['at_ns'] != sample['at_ns']: track.append(sample)
            profile = getattr(d,'profile',None)
            if profile is not None:
                bounds=profile.safety
                info['navigation_bounds']=dict(frame='odom',min_x_m=bounds.min_x_m,max_x_m=bounds.max_x_m,
                    min_y_m=bounds.min_y_m,max_y_m=bounds.max_y_m,min_altitude_m=bounds.min_altitude_m,
                    max_altitude_m=bounds.max_altitude_m)
            # Configured verifier is not itself proof of a fresh valid state.
            configured = getattr(getattr(d, 'ownership', None), 'receive_signing', None) is not None
            verifier = getattr(getattr(d, 'ownership', None), 'receive_signing', None)
            try:
                fresh = bool(info.get('connected') and state and state.health.quality.value == 'VALID' and
                    0 <= self.clock().elapsed_ns_since(state.published_at) <= 3_000_000_000)
            except ValueError: fresh = False
            info.update(world=to_json_value(world), track=list(track), signing_configured=configured,
                verified_frames=0 if verifier is None else verifier.accepted,
                rejected_frames={} if verifier is None else dict(verifier.rejected), fresh_vehicle_state=fresh)
            from vehicle_autonomy.app.web.vehicle_display import vehicle_display
            info['display']=vehicle_display(info,world,profile,self.clock())
            vehicles.append(info)
        return dict(vehicles=vehicles, actions=self.runtime.views(), missions=self.missions.views(),
            resources=self.runtime.resource_view(), manual_sessions=list(self.manual.values()),
            recovered_actions=list(self.recovered_manual.values()), fault=self.control_fault)

    def handle(self, operation, payload):
        if operation == 'console.state':
            if payload: raise ValueError('console snapshot takes no arguments')
            from vehicle_autonomy.app.web.dashboard import dashboard
            with self._control_lock: view=dashboard(self._snapshot(),self.clock())
            tools=getattr(self,'tool_service',None)
            return dict(**view,tools=None if tools is None else tools.snapshot())
        if operation.startswith('tools.') or operation.startswith('workspace.') or operation.startswith('settings.'):
            service=getattr(self,'tool_service',None)
            if service is None: raise ValueError('Tool service not configured; launch with an Agent allowlist')
            return service.handle(operation,payload)
        if operation == 'world.vehicle':
            if set(payload) not in ({'target'},{'target','projection'}) or payload.get('projection','full') not in ('full','ap'): raise ValueError('explicit target/projection required')
            driver=self.drivers[payload['target']]
            view=getattr(driver,'read_view',None)
            info,world=view() if callable(view) else (driver.info(),driver.snapshot())
            verifier=getattr(getattr(driver,'ownership',None),'receive_signing',None)
            projected=(None if world is None else dict(version=to_json_value(world.version),published_at=to_json_value(world.published_at),vehicle=to_json_value(world.vehicle))) if payload.get('projection')=='ap' else to_json_value(world)
            return dict(**info,world=projected,
                signing_configured=verifier is not None,verified_frames=0 if verifier is None else verifier.accepted)
        with self._control_lock:
            if operation == 'studio.state': return self._snapshot()
            if operation == 'mission.library': return list(self.journal.data['versions'].values())
            if operation == 'mission.types': return list(NODE_TYPES)
            if operation == 'mission.validate': return self.missions.validate(payload['spec']).to_dict()
            if operation == 'mission.save':
                spec = self.missions.validate(payload['spec'])
                self.journal.save_version(spec)
                return spec.to_dict()
            if operation == 'mission.start':
                if payload.keys() - {'spec','allow_send','continuation_of'}: raise ValueError('unknown Mission start fields')
                self._require_operational()
                self._idle(payload['spec']['target'], payload.get('continuation_of'))
                return self.missions.start(payload['spec'], allow_send=payload.get('allow_send',False),
                    continuation_of=payload.get('continuation_of'))
            if operation == 'mission.cancel': return self.missions.cancel(payload['id'])
            if operation == 'manual.action' or operation == 'run': return self._manual_action(payload)
            if operation == 'manual.start': return self._manual_action(payload, continuous=True)
            if operation == 'manual.state':
                if set(payload) != {'session_id'}:raise ValueError('manual session required')
                return self.runtime.view(self.manual[payload['session_id']]['action_id'])
            if operation == 'manual.update':
                if set(payload) != {'session_id','sequence','deadline_ns','parameters'}: raise ValueError('strict managed input required')
                self._require_operational()
                s = self.manual[payload['session_id']]
                now = self.clock().monotonic_ns
                if s['last_input_ns'] is not None and now - s['last_input_ns'] < 50_000_000:
                    raise ValueError('manual input rate exceeds 20 Hz')
                if self.drivers[s['target']].info().get('session_id') != s['vehicle_session']:
                    self.runtime.cancel(s['action_id']);raise ValueError('vehicle session changed; reauthorize')
                ticket=payload['deadline_ns']
                if type(ticket) is str:
                    if not re.fullmatch(r'[0-9]{1,20}',ticket):raise ValueError('invalid input deadline ticket')
                    ticket=int(ticket)
                a = self.runtime.update_input(s['action_id'], payload['parameters'], sequence=payload['sequence'],
                    expected_deadline_ns=ticket)
                s['last_input_ns'] = now
                return {k:a[k] for k in ('id','target','state','input_sequence','input_deadline_ns','input_ticket','safety','error')}
            if operation == 'manual.stop':
                if set(payload) != {'session_id'}: raise ValueError('manual session required')
                return self.runtime.cancel(self.manual[payload['session_id']]['action_id'])
            if operation == 'control.reestablish':
                if set(payload) != {'target'}: raise ValueError('target required')
                self._require_operational()
                target = payload['target']
                if any(a['target'] == target and a['kind'] != 'Query' and
                        (a['state'] not in TERMINAL or a['safety'] and not a['safety']['release_safe']) for a in self.runtime.views()):
                    raise ValueError('current Runtime still owns unresolved control')
                if any(m['target'] == target and m['state'] not in TERMINAL for m in self.missions.views()):
                    raise ValueError('Mission still running')
                old_m = [m for m in self.missions.recovered.values() if m['target'] == target and not m['release_safe']]
                old_a = [a for a in self.recovered_manual.values() if a['target'] == target and not a['release_safe']]
                specs = [(n['action'],n['action_version'],m.get('provider_bindings',{}).get(n['action']+'@'+n['action_version']))
                    for m in old_m for n in m['spec']['nodes'] if n['type']=='Action']
                specs += [(a['name'],a.get('version'),a.get('provider_binding')) for a in old_a]
                external_proofs=[]
                for name,version,expected in specs:
                    entry = self.registry.resolve_typed(name,version)
                    if entry.spec.kind.value != 'Query' and entry.spec.external_lifecycle != 'typed_only':
                        store=getattr(entry.factory,'resource_store',None) or getattr(self.drivers[target],'resource_store',None)
                        if expected is None or store is None or store.binding()!=expected or store.records():
                            raise ValueError('external lifecycle needs its pinned trusted Provider reconciliation; ground alone is insufficient')
                        external_proofs.append(dict(binding=expected,proof='valid durable ledger empty after trusted P3 release/reconciliation'))
                evidence = reconstruct(self.drivers[target], [r.get('deployment_identity') for r in old_m+old_a], self.clock())
                evidence['resolved_external_providers']=external_proofs
                def commit(data):
                    for m in old_m:
                        data['runs'][m['id']].update(release_safe=True,continuation_allowed=False,reconstruction=evidence)
                    for identifier,a in self.recovered_manual.items():
                        if a in old_a:
                            data['manual'][identifier].update(release_safe=True,continuation_allowed=False,reconstruction=evidence)
                self.journal.transaction(commit)
                permit = self.missions.restart_permits.get(target)
                if permit:self.runtime.mission_groups.reconstructed(permit)
                for m in old_m: m.update(release_safe=True,continuation_allowed=False,reconstruction=evidence)
                for a in old_a: a.update(release_safe=True,continuation_allowed=False,reconstruction=evidence)
                return evidence
            if operation == 'control.takeover':
                if set(payload) != {'target'}: raise ValueError('target required')
                target = payload['target']
                for m in self.missions.views():
                    if m['target'] == target and (m['state'] not in TERMINAL or not m['release_safe']): self.missions.cancel(m['id'])
                for a in self.runtime.views():
                    if a['target'] == target and a['kind'] != 'Query' and (a['state'] not in TERMINAL or
                            a['safety'] and a['safety']['continuation_allowed']): self.runtime.cancel(a['id'])
                return dict(requested=True, authorization_granted=False, instruction='Wait for trusted safe exit, then explicitly start new control.')
            return super().handle(operation, payload)

    def close(self):
        if self.missions:
            with self._control_lock:
                for m in self.missions.views():
                    if m['state'] not in TERMINAL or not m['release_safe']: self.missions.cancel(m['id'])
        try: super().close()
        finally:
            if self.journal: self.journal.close()


class MissionControlServer(ActionLabServer):
    def __init__(self, address, service, token, audit_path):
        super().__init__(address, service, token, audit_path)
        self.RequestHandlerClass = MissionControlHandler


class MissionControlHandler(ActionLabHandler):
    def do_GET(self):
        static = {'/studio':('mission-studio.html','text/html; charset=utf-8'),
            '/console':('tool-console.html','text/html; charset=utf-8'),
            '/tool-console.js':('tool-console.js','application/javascript'),
            '/tool-console.css':('tool-console.css','text/css'),
            '/control':('manual-control.html','text/html; charset=utf-8'),
            '/mission-ui.css':('mission-ui.css','text/css'),
            '/mission-studio.js':('mission-studio.js','application/javascript'),
            '/manual-control.js':('manual-control.js','application/javascript'),
            '/mission-api.js':('mission-api.js','application/javascript')}
        if self.path in static:
            name, kind = static[self.path]
            self.reply(200, (Path(__file__).parent/'static'/name).read_bytes(), kind);return
        if urlsplit(self.path).path == '/api/world/vehicle':
            if not self.authorized():return
            try:
                query=parse_qs(urlsplit(self.path).query,strict_parsing=True)
                if set(query) not in ({'target'},{'target','projection'}) or len(query['target'])!=1 or 'projection' in query and query['projection']!=['ap']:raise ValueError('explicit target/projection required')
            except ValueError as exc:self.reply(400,dict(ok=False,error=str(exc)));return
            self.invoke('world.vehicle',dict(target=query['target'][0],**({'projection':'ap'} if 'projection' in query else {})));return
        if urlsplit(self.path).path == '/api/manual/state':
            if not self.authorized():return
            try:
                query=parse_qs(urlsplit(self.path).query,strict_parsing=True)
                if set(query)!={'session_id'} or len(query['session_id'])!=1:raise ValueError('one session required')
                identifier=query['session_id'][0]
                if not re.fullmatch(r'manual:[a-f0-9]{32}',identifier):raise ValueError('invalid manual session')
            except ValueError as exc:self.reply(400,dict(ok=False,error=str(exc)));return
            self.invoke('manual.state',dict(session_id=identifier));return
        routes = {'/api/console/state':'console.state','/api/studio/state':'studio.state','/api/missions/library':'mission.library','/api/missions/types':'mission.types'}
        if self.path in routes:
            if self.authorized(): self.invoke(routes[self.path], {})
            return
        super().do_GET()

    max_json_bytes = 131072
    post_routes = dict(ActionLabHandler.post_routes, **{
        '/api/missions/validate':'mission.validate','/api/missions/save':'mission.save',
        '/api/missions/start':'mission.start','/api/missions/cancel':'mission.cancel',
        '/api/manual/action':'manual.action','/api/manual/start':'manual.start',
        '/api/manual/update':'manual.update','/api/manual/stop':'manual.stop',
        '/api/tools/operation':'tools.operation','/api/tools/configure':'tools.configure',
        '/api/settings/context':'settings.context',
        '/api/workspaces/template':'workspace.template','/api/workspaces/save':'workspace.save',
        '/api/workspaces/launch':'workspace.launch','/api/workspaces/stop':'workspace.stop',
        '/api/workspaces/retry':'workspace.retry','/api/workspaces/reconcile':'workspace.reconcile',
        '/api/control/takeover':'control.takeover','/api/control/reestablish':'control.reestablish'})
