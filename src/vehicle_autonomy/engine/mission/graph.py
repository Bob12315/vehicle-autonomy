"""Strict bounded graph validation. A rooted tree has explicit ordered edges.

Repeat provides bounded cycles; graph edges themselves never form cycles or
share mutable node execution identity. Validation also pins Action versions.
"""
from copy import deepcopy
import json
import math
import re
from vehicle_autonomy.contracts.mission import MissionSpec

NODE_TYPES = ('Action', 'Sequence', 'Parallel', 'Condition', 'Fallback', 'Recovery',
              'Event', 'Reactive', 'Wait', 'Timeout', 'Repeat')
IDENTITY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}')
SEMVER = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')


def bounded_number(value, low, high, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(name + ' outside bounds')


def expression_check(e, depth=0):
    if type(e) is not dict or depth > 8: raise ValueError('bounded typed expression required')
    op = e.get('op')
    if op in ('all', 'any'):
        if set(e) != {'op', 'args'} or type(e['args']) is not list or not 1 <= len(e['args']) <= 16:
            raise ValueError('bounded expression arguments required')
        for a in e['args']: expression_check(a, depth + 1)
    elif op == 'not':
        if set(e) != {'op', 'arg'}: raise ValueError('not requires one argument')
        expression_check(e['arg'], depth + 1)
    elif op in ('eq', 'ne', 'lt', 'le', 'gt', 'ge'):
        if e.keys() - {'op', 'source', 'path', 'value', 'frame', 'max_age_s'} or not {'source', 'path', 'value'} <= e.keys():
            raise ValueError('unknown condition fields')
        if e['source'] not in ('world', 'blackboard') or not isinstance(e['path'], str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]{0,127}', e['path']):
            raise ValueError('typed query source/path required')
        if type(e['value']) not in (str, bool, int, float, type(None)): raise ValueError('scalar condition required')
        if 'frame' in e and (not isinstance(e['frame'], str) or not e['frame']): raise ValueError('frame required')
        bounded_number(e.get('max_age_s', 3), .01, 3600, 'condition age')
    else: raise ValueError('unknown typed condition operator')


def validate(document, registry, drivers):
    d = document.to_dict() if isinstance(document, MissionSpec) else deepcopy(document)
    if type(d) is not dict or len(json.dumps(d, allow_nan=False).encode()) > 131072: raise ValueError('bounded Mission object required')
    required = {'schema_version', 'id', 'name', 'version', 'target', 'root', 'nodes'}
    if not required <= d.keys() or d.keys() - required - {'blackboard', 'required_capabilities', 'timeout_s', 'resources'}:
        raise ValueError('missing or unknown Mission fields')
    if type(d['schema_version']) is not int or d['schema_version'] != 1: raise ValueError('unsupported Mission schema')
    if not isinstance(d['id'], str) or not IDENTITY.fullmatch(d['id']): raise ValueError('invalid Mission id')
    if not isinstance(d['name'], str) or not 1 <= len(d['name']) <= 128: raise ValueError('bounded Mission name required')
    if not isinstance(d['version'], str) or len(d['version'])>64 or not SEMVER.fullmatch(d['version']): raise ValueError('semantic Mission version required')
    if d['target'] not in drivers: raise ValueError('unknown Mission target')
    ctx = drivers[d['target']].context()
    capabilities = d.get('required_capabilities', [])
    if type(capabilities) is not list or any(type(c) is not str for c in capabilities) or not set(capabilities) <= ctx.capabilities:
        raise ValueError('Mission capabilities unavailable')
    bounded_number(d.setdefault('timeout_s', 600), .1, 1800, 'Mission timeout')
    if type(d.setdefault('blackboard', {})) is not dict or len(d['blackboard']) > 64: raise ValueError('bounded Blackboard required')
    if any(not IDENTITY.fullmatch(k) for k in d['blackboard']): raise ValueError('invalid Blackboard key')
    if type(d['nodes']) is not list or not 1 <= len(d['nodes']) <= 128: raise ValueError('1..128 nodes required')
    nodes = {}
    derived = set()
    for n in d['nodes']:
        if type(n) is not dict or not isinstance(n.get('id'), str) or not IDENTITY.fullmatch(n['id']) or n['id'] in nodes:
            raise ValueError('unique node identity required')
        if n.get('type') not in NODE_TYPES: raise ValueError('unsupported node type')
        allowed = {'id', 'type', 'children', 'timeout_s', 'position'}
        options = {'Action': {'action', 'action_version', 'parameters', 'output'}, 'Condition': {'expression'},
            'Parallel': {'completion', 'failure'}, 'Event': {'event'}, 'Reactive': {'event'},
            'Wait': {'duration_s'}, 'Repeat': {'count'}}
        if n.keys() - allowed - options.get(n['type'], set()): raise ValueError('unknown node fields: ' + n['id'])
        if 'position' in n:
            if type(n['position']) is not dict or set(n['position']) != {'x', 'y'}: raise ValueError('node layout x/y required')
            for p in n['position'].values(): bounded_number(p, -100000, 100000, 'layout')
        if 'timeout_s' in n: bounded_number(n['timeout_s'], .05, d['timeout_s'], 'node timeout')
        children = n.setdefault('children', [])
        if type(children) is not list or len(set(children)) != len(children) or any(type(c) is not str for c in children):
            raise ValueError('unique ordered child edges required')
        count = len(children)
        t = n['type']
        if t in ('Action', 'Wait') and count: raise ValueError('leaf cannot have children')
        if t in ('Sequence', 'Parallel', 'Fallback', 'Recovery') and not 1 <= count <= 32: raise ValueError('bounded composite children required')
        if t in ('Timeout', 'Repeat', 'Event') and count != 1: raise ValueError('one child required')
        if t == 'Reactive' and count != 2: raise ValueError('Reactive requires main and response children')
        if t == 'Condition' and count not in (0, 2, 3): raise ValueError('Condition requires zero, two or three branches')
        if t == 'Condition': expression_check(n.get('expression'))
        if t == 'Parallel':
            if n.setdefault('completion', 'all') not in ('all', 'any', 'main') or n.setdefault('failure', 'fail_fast') not in ('fail_fast', 'all_failed'):
                raise ValueError('explicit Parallel policies required')
        if t == 'Wait': bounded_number(n.get('duration_s'), 0, d['timeout_s'], 'wait')
        if t == 'Timeout' and 'timeout_s' not in n: raise ValueError('Timeout duration required')
        if t == 'Repeat' and (type(n.get('count')) is not int or not 1 <= n['count'] <= 20): raise ValueError('Repeat count must be 1..20')
        if t in ('Event', 'Reactive') and (not isinstance(n.get('event'), str) or not IDENTITY.fullmatch(n['event'])):
            raise ValueError('event name required')
        if t == 'Action':
            name = n.get('action')
            entry = registry.resolve_typed(name, n.get('action_version'))
            n['action_version'] = entry.spec.version
            params = deepcopy(n.setdefault('parameters', {}))
            if type(params) is not dict: raise ValueError('Action parameters must be an object')
            schema = registry.metadata(name, n['action_version'], vehicle_kind=ctx.target_kind)['parameters']
            for field, value in params.items():
                if type(value) is not dict or '$query' not in value: continue
                if set(value) != {'$query'} or type(value['$query']) is not dict: raise ValueError('strict parameter binding required')
                q = value['$query']
                check = {k: v for k, v in q.items() if k != 'offset'}
                expression_check(dict(check, op='eq', value=0))
                if q.keys() - {'source','path','frame','max_age_s','offset'}: raise ValueError('unknown query binding fields')
                if 'offset' in q: bounded_number(q['offset'], -1000000, 1000000, 'parameter offset in declared field units')
                prop = schema['properties'].get(field)
                if prop is None: raise ValueError('unknown bound Action parameter')
                if prop.get('type') not in ('integer','number','string','boolean'): raise ValueError('scalar binding required')
                params[field] = prop.get('const', prop.get('default', prop.get('enum', [None])[0]))
                if params[field] is None:
                    params[field] = {'integer': 0, 'number': 0., 'string': '', 'boolean': False}[prop['type']]
                    if 'minimum' in prop: params[field] = prop['minimum']
                    if 'exclusiveMinimum' in prop: params[field] = prop['exclusiveMinimum'] + 1
            registry.parameters(name, params, n['action_version'], vehicle_kind=ctx.target_kind)
            if entry.spec.vehicle_types and ctx.target_kind not in entry.spec.vehicle_types: raise ValueError('unsupported Action vehicle')
            if not entry.spec.required_capabilities <= ctx.capabilities: raise ValueError('Action capabilities unavailable')
            if 'output' in n and (not isinstance(n['output'], str) or not IDENTITY.fullmatch(n['output'])): raise ValueError('invalid output key')
            derived.update(r.name for r in entry.spec.resources)
        nodes[n['id']] = n
    if d['root'] not in nodes: raise ValueError('root node unavailable')
    seen = set()
    def visit(identifier, depth=0, multiplier=1):
        if identifier in seen or identifier not in nodes or depth > 16: raise ValueError('cycle/shared/orphan edge or depth limit')
        seen.add(identifier)
        n = nodes[identifier]
        cost = multiplier if n['type'] == 'Action' else 0
        for child in n['children']: cost += visit(child, depth + 1, multiplier * (n.get('count', 1) if n['type'] == 'Repeat' else 1))
        return cost
    if visit(d['root']) > 256 or len(seen) != len(nodes): raise ValueError('orphan nodes or total Action budget exceeded')
    def declared(identifier):
        n = nodes[identifier]
        if n['type'] == 'Action':
            s = registry.resolve_typed(n['action'], n['action_version']).spec
            return tuple((r.conflict_group or r.name, r.mode.value) for r in s.resources)
        return tuple(v for c in n['children'] for v in declared(c))
    def query_only(identifier):
        n = nodes[identifier]
        if n['type'] == 'Action':
            return registry.resolve_typed(n['action'], n['action_version']).spec.kind.value == 'Query'
        return all(query_only(c) for c in n['children'])
    for n in nodes.values():
        if n['type'] == 'Condition' and len(n['children']) == 3 and not query_only(n['children'][2]):
            raise ValueError('UNKNOWN condition branch may only query/wait; no new side effects')
        if n['type'] == 'Parallel':
            branches = [declared(c) for c in n['children']]
            for i, left in enumerate(branches):
                for right in branches[i+1:]:
                    if any(a == b and ('exclusive' in (am, bm)) for a, am in left for b, bm in right):
                        raise ValueError('Parallel has conflicting registered resources')
    resources = d.get('resources', sorted(derived))
    if type(resources) is not list or set(resources) != derived: raise ValueError('Mission resources must match registered Action requirements')
    d['resources'] = sorted(derived)
    return MissionSpec(d)
