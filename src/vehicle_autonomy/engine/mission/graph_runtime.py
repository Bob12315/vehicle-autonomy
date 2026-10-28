"""Bounded Mission graph scheduler. The only side-effect port is ActionRuntime.

The application calls tick BEFORE ActionRuntime.tick, committing Action IDs and
intent before any Action callback can emit effects. UNKNOWN is not recovery.
"""
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from uuid import uuid4
from datetime import datetime
from vehicle_autonomy.contracts.core.time import TimePoint

from vehicle_autonomy.contracts.mission import BlackboardValue, Truth
from vehicle_autonomy.contracts.action import ActionResource, ResourceMode
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.engine.mission.graph import validate
from vehicle_autonomy.world.model.mission_inputs import evaluate, resolve_parameters

TERMINAL = {'SUCCEEDED', 'FAILED', 'REJECTED', 'CANCELLED', 'TIMED_OUT', 'UNKNOWN'}


@dataclass
class NodeRun:
    id: str
    execution_id: str = field(default_factory=lambda: 'node:' + uuid4().hex)
    state: str = 'IDLE'
    started_ns: int | None = None
    action_id: str | None = None
    index: int = 0
    truth: str | None = None
    pending_end: str | None = None
    event_id: str | None = None
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)


class GraphRun:
    def __init__(self, spec, now, cursor, allow_send, continuation):
        self.spec = spec.to_dict()
        self.id = 'mission-run:' + uuid4().hex
        self.state = 'RUNNING'
        self.started = now
        self.deadline_ns = now.monotonic_ns + int(self.spec['timeout_s'] * 1e9)
        self.nodes = {n['id']: n for n in self.spec['nodes']}
        self.runs = {n: NodeRun(n) for n in self.nodes}
        self.blackboard = {k: BlackboardValue(v, now, int(self.spec['timeout_s'] * 1e9)) for k, v in self.spec['blackboard'].items()}
        self.event_cursors = {n: cursor for n in self.nodes}
        self.allow_send = allow_send
        self.continuation = continuation
        self.actions = []
        self.action_bindings = []
        self.history = deque(maxlen=256)
        self.cancel_to = None
        self.error = None


class MissionGraphRuntime:
    def __init__(self, actions, journal, events, *, clock, deployment_identities=None, recovered_manual=None):
        self.actions, self.journal, self.events, self.clock = actions, journal, events, clock
        self.identities = deepcopy(deployment_identities or {})
        self.runs = {}
        self.recovered = deepcopy(journal.data['runs'])
        # No old Action, authorization, lease or session is reconstructed.
        for v in self.recovered.values():
            if v['state'] not in TERMINAL or not v.get('release_safe', False):
                v.update(state='UNKNOWN', release_safe=False, continuation_allowed=False,
                         error='application restarted; trusted reconstruction and new authorization required')
                journal.save_run(v)
        self.restart_permits = {}
        by_target = {}
        for v in list(self.recovered.values()) + list((recovered_manual or {}).values()):
            if v.get('release_safe', False): continue
            claims = v.get('resource_claims')
            if claims is None:
                claims = to_json_value(self.declarations(v['spec'])) if 'spec' in v else to_json_value(
                    self.actions.registry.resolve_typed(v['name'], v.get('version')).spec.resources)
            by_target.setdefault(v['target'], []).extend(ActionResource(c['name'],ResourceMode(c['mode']),c['conflict_group']) for c in claims)
        for target, claims in by_target.items():
            self.restart_permits[target] = actions.mission_groups.reserve('restart-group:'+uuid4().hex,target,
                self.merge_resources(claims),recovered=True)

    @staticmethod
    def merge_resources(resources):
        result = {}
        for r in resources:
            key = r.conflict_group or r.name
            if key not in result or r.mode is ResourceMode.EXCLUSIVE: result[key] = r
        return tuple(result.values())

    def declarations(self, document):
        d = document.to_dict() if hasattr(document,'to_dict') else document
        return self.merge_resources(r for n in d['nodes'] if n['type']=='Action'
            for r in self.actions.registry.resolve_typed(n['action'],n['action_version']).spec.resources)

    def validate(self, document):
        return validate(document, self.actions.registry, self.actions.drivers)

    def start(self, document, *, allow_send=False, continuation_of=None, debug=False):
        if type(allow_send) is not bool: raise ValueError('explicit Mission SEND bool required')
        if type(debug) is not bool:raise ValueError('explicit debug bool required')
        spec = self.validate(document)
        d = spec.to_dict()
        for old in self.views():
            if old['target'] == d['target'] and (old['state'] not in TERMINAL or not old['release_safe']):
                if not (old['continuation_allowed'] and old['continuation_of'] == continuation_of):
                    raise ValueError('target owned by active/uncertain Mission')
        if len(self.journal.data['runs']) >= 64: raise ValueError('Mission history budget exhausted')
        self.journal.save_version(spec)
        r = GraphRun(spec, self.clock(), self.events.cursor, allow_send, continuation_of)
        r.studio=None
        if 'studio' in r.spec:
            from .studio_state import StudioState
            r.history=deque(maxlen=4096);r.studio=StudioState(self,r,self.clock());r.debug=debug
        r.provider_bindings = {}
        for n in d['nodes']:
            if n['type'] != 'Action':continue
            entry=self.actions.registry.resolve_typed(n['action'],n['action_version'])
            store=getattr(entry.factory,'resource_store',None) or getattr(self.actions.drivers[d['target']],'resource_store',None)
            if entry.spec.kind.value!='Query' and entry.spec.external_lifecycle!='typed_only':
                r.provider_bindings[n['action']+'@'+n['action_version']]=None if store is None else store.binding()
        r.deployment_identity = deepcopy(self.identities.get(d['target']))
        r.permit = self.actions.mission_groups.reserve(r.id,d['target'],self.declarations(spec),
            allow_send=allow_send,continuation_of=continuation_of)
        self.runs[r.id] = r
        self._event(r, 'mission_started', version=d['version'])
        self._persist(r)
        return self.view(r.id)

    def busy(self, target):
        return any(v['target'] == target and (v['state'] not in TERMINAL or not v.get('release_safe', False))
                   for v in self.views())

    def _event(self, r, event, **values):
        if 'studio' in r.spec:
            if len(r.history)>=r.history.maxlen:raise ValueError('Mission event history budget exhausted')
            r.event_counter=getattr(r,'event_counter',0)+1
            values=dict(id=r.id+':event:'+str(r.event_counter),sequence=r.event_counter,**values)
        r.history.append(dict(event=event, at_ns=self.clock().monotonic_ns, **values))

    def _set(self, r, n, state):
        if n.state != state:
            n.state = state
            self._event(r, 'node_state', node_id=n.id, execution_id=n.execution_id, state=state, action_id=n.action_id)

    def _action_safe(self, a):
        return a['state'] == 'REJECTED' or bool(a['safety'] and a['safety']['release_safe'])

    def _children(self, r, key):
        yield r.runs[key]
        for child in r.nodes[key]['children']: yield from self._children(r, child)

    def _cancel_tree(self, r, key, outcome='CANCELLED'):
        nodes = tuple(self._children(r, key))
        pending, uncertain = False, False
        for n in nodes:
            if not n.action_id: continue
            a = self.actions.assess(n.action_id)
            if (outcome == 'SUCCEEDED' and a['id'] == r.continuation and a['state'] == 'SUCCEEDED'
                    and a['safety'] and a['safety']['continuation_allowed']): continue
            if not self._action_safe(a):
                self.actions.cancel(n.action_id)
                a = self.actions.assess(n.action_id)
                if a['state'] not in TERMINAL: pending = True
                elif not self._action_safe(a): uncertain = True
        state = 'CANCELLING' if pending else 'UNKNOWN' if uncertain else outcome
        for n in nodes:
            if n.state not in TERMINAL or n.id == key: self._set(r, n, state)
        return state

    def cancel(self, identifier, *, outcome='CANCELLED'):
        if identifier in self.recovered: return self.view(identifier)
        r = self.runs[identifier]
        if r.state in TERMINAL and self.view(identifier)['release_safe']: return self.view(identifier)
        r.cancel_to = outcome
        r.state = 'CANCELLING'
        self._persist(r)
        return self.view(identifier)

    def _reset(self, r, key):
        for n in tuple(self._children(r, key)):
            if r.studio:r.studio.archive(n)
            r.runs[n.id] = NodeRun(n.id)

    def _tick_node(self, r, key, now):
        n, spec = r.runs[key], r.nodes[key]
        if n.state=='SKIPPED':return 'SUCCEEDED'
        if n.details.get('debug_failed'):return 'RUNNING'
        if n.state in TERMINAL: return n.state
        if n.state == 'IDLE':
            if r.studio and r.studio.gate(key):return 'RUNNING'
            n.started_ns = now.monotonic_ns
            self._set(r, n, 'RUNNING')
        timeout = spec.get('timeout_s')
        if timeout is not None and now.monotonic_ns - n.started_ns >= int(timeout * 1e9):
            n.pending_end = 'TIMED_OUT'
        if n.pending_end:
            state = self._cancel_tree(r, key, n.pending_end)
            if state != 'CANCELLING': self._set(r, n, state)
            return state
        t, children = spec['type'], spec['children']
        result = 'RUNNING'
        if t=='Result':result=spec['outcome']
        elif t == 'Action':
            if n.action_id is None:
                if len(r.actions) >= 256: raise ValueError('Mission Action budget exceeded')
                self._event(r, 'action_intent', node_id=key)
                self._persist(r)
                registration = self.actions.registry.resolve_typed(spec['action'], spec['action_version'])
                transfer = r.continuation if registration.spec.effect_types else None
                world = self.actions.drivers[r.spec['target']].snapshot()
                now = self.clock()
                try:
                    parameters=(r.studio.resolve(spec['parameters'],key,world,now) if r.studio else resolve_parameters(spec['parameters'], world, r.blackboard, now))
                    if r.studio:parameters.update(r.studio.overrides.get(key,{}))
                except ValueError:
                    n.truth = 'UNKNOWN'
                    if now.monotonic_ns - n.started_ns < 3_000_000_000: return 'RUNNING'
                    raise
                a = self.actions.submit(spec['action'], r.spec['target'], parameters,
                    version=spec['action_version'], allow_send=r.allow_send,
                    timeout_s=min(spec.get('timeout_s', 1800), (r.deadline_ns - now.monotonic_ns) / 1e9,
                        self.actions.registry.metadata(spec['action'], spec['action_version'],
                            vehicle_kind=self.actions.drivers[r.spec['target']].context().target_kind)['default_timeout_s']),
                    continuation_of=transfer,mission_permit=r.permit)
                n.action_id = a['id']; r.actions.append(a['id'])
                r.action_bindings.append(dict(node_id=key,execution_id=n.execution_id,action_id=a['id'],submitted_at_ns=now.monotonic_ns))
                if transfer is not None: r.continuation = None
                self._persist(r)
            a = self.actions.assess(n.action_id)
            result = a['state'] if a['state'] in TERMINAL else 'RUNNING'
            if result == 'SUCCEEDED':
                if a['safety'] and a['safety']['continuation_allowed']:
                    r.continuation = a['id']
                elif not self._action_safe(a): result = 'UNKNOWN'
                if r.studio and result=='SUCCEEDED':r.studio.action_result(key,self.actions.assess(n.action_id,include_result=True),now)
                if 'output' in spec:
                    a=self.actions.assess(n.action_id,include_result=True)
                    stamp = a['result_at']
                    if stamp is None: raise ValueError('Action output has no original result timestamp')
                    observed = TimePoint(stamp['monotonic_ns'],datetime.fromisoformat(stamp['utc']),stamp['clock_domain_id'])
                    r.blackboard[spec['output']] = BlackboardValue(a['result'], observed, 3_000_000_000, source=a['id'])
            elif result in TERMINAL and not self._action_safe(a): result = 'UNKNOWN'
            if r.studio and r.debug and result in ('FAILED','TIMED_OUT') and self._action_safe(a):
                self._set(r,n,result);n.details['debug_failed']=True;r.studio.pause_requested=True
                self._event(r,'debug_failure',node_id=spec['source_node_id'],execution_id=n.execution_id,state=result)
                return 'RUNNING'
        elif t == 'Wait':
            if now.monotonic_ns - n.started_ns >= int(spec['duration_s'] * 1e9): result = 'SUCCEEDED'
        elif t == 'Condition':
            if n.truth is None:
                world = self.actions.drivers[r.spec['target']].snapshot()
                n.truth = self._evaluate(r,key,spec['expression'],world,self.clock()).value
            if not children: result = {'TRUE': 'SUCCEEDED', 'FALSE': 'FAILED', 'UNKNOWN': 'UNKNOWN'}[n.truth]
            elif n.truth == 'UNKNOWN' and len(children) != 3: result = 'UNKNOWN'
            else: result = self._tick_node(r, children[{'TRUE': 0, 'FALSE': 1, 'UNKNOWN': 2}[n.truth]], now)
        elif t in ('Sequence', 'Fallback', 'Recovery'):
            # At most one new sequential child per scheduler cycle.
            result = self._tick_node(r, children[n.index], now)
            if result == 'UNKNOWN': pass
            elif t == 'Sequence':
                if result == 'SUCCEEDED' and n.index < len(children) - 1:
                    n.index += 1; result = 'RUNNING'
            elif result in TERMINAL and result != 'SUCCEEDED':
                if n.index < len(children) - 1: n.index += 1; result = 'RUNNING'
        elif t == 'Parallel':
            if r.studio and 'branches' not in n.details:
                n.details['branches']=[r.studio.board.create('parallel',r.studio.context(key),{},now) for c in children]
                for c,scope in zip(children,n.details['branches']):r.studio.assign(c,scope)
            capacity=spec.get('max_concurrency',len(children));active=sum(r.runs[c].state not in TERMINAL|{'IDLE','SKIPPED'} for c in children);values=[]
            for c in children:
                if r.runs[c].state=='IDLE' and active>=capacity:values.append('RUNNING');continue
                initial=r.runs[c].state=='IDLE';value=self._tick_node(r,c,now);values.append(value)
                if initial and value not in TERMINAL:active+=1
            if 'UNKNOWN' in values: chosen = 'UNKNOWN'
            elif spec['failure'] == 'fail_fast' and any(v in TERMINAL - {'SUCCEEDED'} for v in values): chosen = 'FAILED'
            elif spec['completion'] == 'any' and 'SUCCEEDED' in values: chosen = 'SUCCEEDED'
            elif spec['completion'] == 'main' and values[0] in TERMINAL: chosen = values[0]
            elif all(v in TERMINAL for v in values): chosen = 'SUCCEEDED' if all(v == 'SUCCEEDED' for v in values) else 'FAILED'
            else: chosen = None
            if chosen:
                # Retained successful Plane scopes are not implicitly cancelled
                # to make a race look safe. Such a graph remains UNKNOWN.
                n.pending_end = chosen
                state = self._cancel_tree(r, key, chosen)
                result = chosen if state == chosen else state
                if r.studio and result=='SUCCEEDED' and not n.details.get('committed'):
                    selected=[scope for scope,value in zip(n.details['branches'],values) if value=='SUCCEEDED']
                    r.studio.board.commit(selected)
                    for scope in n.details['branches']:r.studio.board.scopes[scope]['closed']=True
                    n.details['committed']=True
        elif t=='ForEach':
            if not r.studio.foreach_scope(key,now):result='SUCCEEDED'
            else:
                child=children[0];value=self._tick_node(r,child,now)
                if value in TERMINAL:
                    scope=n.details['iteration_scopes'][n.index]
                    r.studio.board.scopes[scope]['closed']=True
                    self._event(r,'iteration_completed',node_id=spec['source_node_id'],execution_id=n.execution_id,index=n.index,scope_id=scope,state=value)
                    if value=='UNKNOWN' or value!='SUCCEEDED' and spec['on_item_failure']=='abort':result=value
                    else:
                        n.index+=1
                        if n.index<len(n.details['items']):self._reset(r,child)
                        else:result='SUCCEEDED'
        elif t=='SubMission':
            r.studio.submission_enter(key,now);result=self._tick_node(r,children[0],now)
            if result=='SUCCEEDED':r.studio.submission_exit(key,now)
        elif t=='Retry':
            result=self._tick_node(r,children[0],now)
            if result in ('FAILED','TIMED_OUT') and n.index+1<spec['count']:
                if any(child.action_id and not self._action_safe(self.actions.assess(child.action_id)) for child in self._children(r,children[0])):result='UNKNOWN'
                else:n.index+=1;self._reset(r,children[0]);result='RUNNING'
        elif t=='Await':
            if 'expression' in spec:
                world=self.actions.drivers[r.spec['target']].snapshot();n.truth=self._evaluate(r,key,spec['expression'],world,now).value
                if n.truth=='TRUE':result='SUCCEEDED'
            else:
                events=self.events.read(r.event_cursors[key],spec['event'],now)
                if events:n.event_id=events[0].id;r.event_cursors[key]=events[0].sequence;result='SUCCEEDED'
        elif t == 'Repeat':
            result = self._tick_node(r, children[0], now)
            if result == 'SUCCEEDED' and n.index + 1 < spec['count']:
                n.index += 1; self._reset(r, children[0]); result = 'RUNNING'
        elif t == 'Timeout': result = self._tick_node(r, children[0], now)
        elif t in ('Event', 'Reactive'):
            if n.event_id is None:
                events = self.events.read(r.event_cursors[key], spec['event'], now)
                if events:
                    e = events[0]; n.event_id = e.id; r.event_cursors[key] = e.sequence
                    r.blackboard['event'] = e.data
                    self._event(r, 'event_consumed', node_id=key, event_id=e.id, sequence=e.sequence)
            if t == 'Event':
                if n.event_id is not None: result = self._tick_node(r, children[0], now)
            elif n.event_id is None: result = self._tick_node(r, children[0], now)
            else:
                stopped = self._cancel_tree(r, children[0])
                if stopped == 'CANCELLED': result = self._tick_node(r, children[1], now)
                else: result = 'UNKNOWN' if stopped == 'UNKNOWN' else 'RUNNING'
        if result in TERMINAL: self._set(r, n, result)
        return result

    def tick(self):
        for r in tuple(self.runs.values()):
            if r.state in TERMINAL:
                view = self.view(r.id)
                if self.journal.data['runs'].get(r.id) != view:self.journal.save_run(view)
                continue
            now = self.clock()
            try:
                elapsed = now.elapsed_ns_since(r.started)
                if elapsed < 0: r.cancel_to = 'UNKNOWN'
                if now.monotonic_ns >= r.deadline_ns: r.cancel_to = 'TIMED_OUT'
                if r.cancel_to:
                    state = self._cancel_tree(r, r.spec['root'], r.cancel_to)
                    r.state = state
                elif r.state=='PAUSED':
                    self._persist(r);continue
                elif r.studio and r.studio.pause_requested and r.studio.safe_boundary():r.state='PAUSED'
                else:
                    state = self._tick_node(r, r.spec['root'], now)
                    if state in TERMINAL:
                        if state != 'SUCCEEDED':
                            # Always clean up every active descendant before a
                            # failure/UNKNOWN is reported as released.
                            r.cancel_to = state
                            r.state = self._cancel_tree(r, r.spec['root'], state)
                        else: r.state = state
                    elif r.studio and r.studio.pause_requested and r.studio.safe_boundary():r.state='PAUSED'
                if r.state in TERMINAL:
                    self.actions.mission_groups.finish(r.permit,continuation=self.view(r.id)['continuation_allowed'])
                self._persist(r)
            except Exception as exc:
                r.error = type(exc).__name__ + ': ' + str(exc)[:300]
                r.cancel_to = 'UNKNOWN'
                r.state = self._cancel_tree(r, r.spec['root'], 'UNKNOWN')
                self.actions.mission_groups.finish(r.permit)
                self._persist(r)  # Persistence failure propagates: owner must fence all Actions.

    def view(self, identifier):
        if identifier in self.recovered: return deepcopy(self.recovered[identifier])
        r = self.runs[identifier]
        views = [self.actions.assess(a) for a in r.actions]
        safe = all(self._action_safe(a) for a in views)
        latest = None if r.continuation is None else self.actions.assess(r.continuation)
        continuation = r.state == 'SUCCEEDED' and not safe and latest is not None and latest['safety'] and latest['safety']['continuation_allowed'] and all(
            self._action_safe(a) or a['state'] == 'SUCCEEDED' and a['safety'] and a['safety']['continuation_allowed'] for a in views)
        result=dict(id=r.id, mission_id=r.spec['id'], version=r.spec['version'], target=r.spec['target'],
            provider_bindings=deepcopy(r.provider_bindings),resource_claims=to_json_value(r.permit.resources),resource_group_id=r.permit.id,
            deployment_identity=deepcopy(r.deployment_identity), state=r.state, release_safe=safe, continuation_allowed=bool(continuation), continuation_of=r.continuation,
            error=r.error, deadline_ns=r.deadline_ns, spec=deepcopy(r.spec),
            blackboard=to_json_value(r.blackboard),
            nodes=[dict(id=n.id, execution_id=n.execution_id, state=n.state, action_id=n.action_id, truth=n.truth,
                        iteration=n.index, event_id=n.event_id) for n in r.runs.values()],
            action_ids=list(r.actions), action_bindings=deepcopy(r.action_bindings), history=list(r.history))
        if r.studio:result['studio']=r.studio.snapshot(self.clock())
        return result

    def _evaluate(self,r,key,expression,world,now):
        resolver=None
        if r.studio:
            def resolver(e):
                try:return r.studio.board.read(r.studio.context(key),dict(source='world',path=e['path']) if e['source']=='world' else dict(ref=e['path']),now,world)[1]
                except ValueError:return None
        return evaluate(expression,world,r.blackboard,now,resolver=resolver)

    def views(self):
        return [self.view(k) for k in self.recovered] + [self.view(k) for k in self.runs]

    def debug(self,identifier,operation,*,node_id=None,parameters=None):
        if identifier not in self.runs:raise ValueError('recovered runs are observational; new validation/authorization required')
        r=self.runs[identifier];s=r.studio
        if s is None:raise ValueError('Studio debug requires a schema-2 publication')
        if r.state in TERMINAL:raise ValueError('terminal/uncertain run cannot be resumed by debug')
        if operation=='pause':
            s.pause_requested=True;r.state='PAUSE_REQUESTED';self._event(r,'pause_requested')
        elif operation=='breakpoints':
            values=parameters
            ids={n.get('source_node_id') for n in r.nodes.values()}
            if type(values) is not list or len(values)>128 or any(type(v) is not str or v not in ids for v in values):raise ValueError('bounded existing breakpoint nodes required')
            s.breakpoints=set(values);self._event(r,'breakpoints_changed',nodes=values)
        else:
            if r.state!='PAUSED' or not s.safe_boundary():raise ValueError('confirmed safe paused boundary required')
            if operation in ('resume','step'):
                if any(n.details.get('debug_failed') for n in r.runs.values()):raise ValueError('resolve failed node with permitted retry/skip before resume')
                driver=self.actions.drivers[r.spec['target']];world=driver.snapshot();now=self.clock()
                if world is None or not 0<=now.elapsed_ns_since(world.published_at)<3_000_000_000:raise ValueError('fresh state required before resume')
                info=driver.info() if callable(getattr(driver,'info',None)) else {}
                epoch=(info.get('session_id'),str(getattr(getattr(world,'version',None),'generation_id',None)))
                if epoch!=s.vehicle_epoch:raise ValueError('vehicle session/origin changed; create a newly validated run')
                if getattr(world,'vehicle',None) is not None and world.vehicle.health.quality.value!='VALID':raise ValueError('valid vehicle state required')
                s.pause_requested=False;s.step_remaining=None if operation=='resume' else (0 if any(n.state=='RUNNING' and r.nodes[n.id]['type'] in ('Wait','Await') for n in r.runs.values()) else 1)
                r.state='RUNNING';self._event(r,'mission_'+operation)
            elif operation in ('retry','skip','override'):
                choices=[n for n in r.runs.values() if n.id==node_id or r.nodes[n.id].get('source_node_id')==node_id and r.nodes[n.id]['type'] in ('Action','Wait','Await')]
                if len(choices)!=1:raise ValueError('one unambiguous runtime node required')
                n=choices[0];spec=r.nodes[n.id]
                if operation=='retry':
                    if not n.details.get('debug_failed') or spec['type']!='Action' or not self.actions.registry.resolve_typed(spec['action'],spec['action_version']).spec.retryable:raise ValueError('node/Action contract does not permit retry')
                    attempts=n.details.get('debug_retries',0)
                    if attempts>=2 or n.action_id and not self._action_safe(self.actions.assess(n.action_id)):raise ValueError('retry budget or physical exit barrier')
                    self._reset(r,n.id);r.runs[n.id].details['debug_retries']=attempts+1
                elif operation=='skip':
                    if n.state!='IDLE' and not n.details.get('debug_failed'):raise ValueError('only pending or safely failed nodes may be skipped')
                    if spec['type'] not in ('Wait','Await') and not spec.get('skippable'):raise ValueError('published node/Action contract forbids skip')
                    n.details.pop('debug_failed',None);self._set(r,n,'SKIPPED')
                else:
                    if n.state!='IDLE' or spec['type']!='Action' or type(parameters) is not dict or not parameters or parameters.keys()-set(spec.get('runtime_overrides',[])):raise ValueError('only declared pending parameters may be overridden')
                    from vehicle_autonomy.engine.action.schema import validate_json
                    schema=self.actions.registry.metadata(spec['action'],spec['action_version'],vehicle_kind=self.actions.drivers[r.spec['target']].context().target_kind)['parameters']
                    for name,value in parameters.items():validate_json(value,schema['properties'][name],name)
                    s.overrides[n.id]=dict(s.overrides.get(n.id,{}),**deepcopy(parameters))
                self._event(r,'debug_'+operation,node_id=spec.get('source_node_id'),execution_id=n.execution_id,parameters=deepcopy(parameters))
            else:raise ValueError('unsupported debug operation')
        self._persist(r);return self.view(identifier)

    def _persist(self, r):
        view = self.view(r.id)
        if self.journal.data['runs'].get(r.id) != view:self.journal.save_run(view)
