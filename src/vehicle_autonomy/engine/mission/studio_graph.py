"""Authoritative schema-2 graph compiler into the existing Mission scheduler.

Graphs are structured control flow, never arbitrary code. The emitted tree is
derived data; its embedded canonical definition and dependencies remain pinned.
"""
from copy import deepcopy
import hashlib,json,re

from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.engine.action.schema import validate_json
from .blackboard import declaration,subschema
from .graph import IDENTITY,SEMVER,bounded_number,expression_check

NODE_ID=re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}')
TYPES={
 'Start':dict(ports=['next'],category='flow'), 'End':dict(ports=[],category='flow'),
 'Action':dict(ports=['next','failure'],category='action'),
 'Condition':dict(ports=['true','false','unknown','next'],category='logic'),
 'ForEach':dict(ports=['body','next'],category='loop'),
 'Parallel':dict(ports=['branch:*','next'],category='parallel'),
 'Join':dict(ports=['next'],category='parallel'),
 'Wait':dict(ports=['next'],category='wait'),
 'SubMission':dict(ports=['next','failure'],category='composite'),
 'Sequence':dict(ports=['child:*','next'],category='logic'),
 'Recovery':dict(ports=['try','recover','next'],category='logic'),
 'Retry':dict(ports=['body','next'],category='logic')}


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def compatible(source,target):
    if 'anyOf' in source:return all(compatible(c,target) for c in source['anyOf'])
    if 'anyOf' in target:return any(compatible(source,c) for c in target['anyOf'])
    a,b=source.get('type'),target.get('type')
    if a is None and 'const' in source:a={bool:'boolean',int:'integer',float:'number',str:'string',type(None):'null'}.get(type(source['const']))
    if a is None and 'enum' in source and source['enum']:a={bool:'boolean',int:'integer',float:'number',str:'string'}.get(type(source['enum'][0]))
    if a!=b and (a,b)!=('integer','number'):return False
    if b=='array':return compatible(source.get('items',{}),target.get('items',{}))
    if b=='object':return all(k in source.get('properties',{}) and compatible(source['properties'][k],target.get('properties',{}).get(k,{})) for k in target.get('required',[]))
    return a is not None


WORLD_TYPES={
 'vehicle.operation.armed':{'type':'boolean'},'vehicle.operation.native_mode':{'type':'string'},
 'vehicle.vehicle_id':{'type':'string'},'vehicle.health.quality':{'type':'string'}}
for field in ('x','y','z'):WORLD_TYPES['vehicle.reported_pose.value.position.'+field]={'type':'number'}
for field in ('x','y','z'):WORLD_TYPES['vehicle.reported_twist.value.linear.'+field]={'type':'number'}
for field in ('latitude_deg','longitude_deg','altitude_amsl_m'):WORLD_TYPES['vehicle.global_position.value.'+field]={'type':'number'}


def binding_schema(binding,variables,outputs):
    if type(binding) is not dict or binding.keys()-{'ref','source','path','max_age_s','frame','offset','provider','id'}:raise ValueError('strict data binding required')
    bounded_number(binding.get('max_age_s',3),.01,3600,'binding freshness')
    if binding.get('source') not in (None,'blackboard','world','external'):raise ValueError('unknown data binding source')
    if binding.get('source')!='external' and ('provider' in binding or 'id' in binding):raise ValueError('external identity only belongs to external input bindings')
    if binding.get('source')=='external':
        if binding.get('provider')!='navigation_goal' or type(binding.get('id')) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',binding['id']) or binding.get('path') not in ('position.x','position.y','position.z') or binding.get('frame')!='odom':raise ValueError('qualified navigation input reference required')
        if binding.get('max_age_s',30)>30:raise ValueError('navigation proposal validity cannot be extended')
        result={'type':'number'}
    elif binding.get('source')=='world':
        if binding.get('path') not in WORLD_TYPES:raise ValueError('world binding path has no declared scalar contract')
        result=WORLD_TYPES[binding['path']]
    else:
        ref=binding.get('ref')
        if type(ref) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,255}',ref):raise ValueError('bounded scoped reference required')
        parts=ref.split('.')
        if parts[0]=='node':
            if len(parts)<3 or parts[2]!='output' or parts[1] not in outputs:raise ValueError('declared upstream node output required')
            if outputs[parts[1]] is None:raise ValueError('upstream Action has no declared output schema; diagnostic data cannot be bound')
            result=subschema(outputs[parts[1]],parts[3:])
        else:
            root='.'.join(parts[:2])
            if root not in variables:raise ValueError('binding variable is not declared: '+root)
            result=subschema(variables[root]['schema'],parts[2:])
            expected=variables[root].get('frame')
            if binding.get('frame') and expected!=binding['frame']:raise ValueError('binding coordinate frame mismatch')
    if 'offset' in binding:
        bounded_number(binding['offset'],-1e6,1e6,'binding offset')
        if result.get('type') not in ('integer','number'):raise ValueError('numeric binding offset required')
        if result.get('type')=='integer' and type(binding['offset']) is float:result={'type':'number'}
    return result


def normalize(document):
    d=deepcopy(document)
    required={'schema_version','mission_id','revision','version','name','target','supported_vehicles','nodes','edges'}
    if type(d) is not dict or not required<=d.keys() or d.keys()-required-{'blackboard','execution_policy','resource_requirements','failure_policy','sub_mission_references','metadata','interface'}:raise ValueError('missing or unknown Studio definition fields')
    if d['schema_version']!=2 or type(d['schema_version']) is not int:raise ValueError('Studio schema_version=2 required')
    if not IDENTITY.fullmatch(d['mission_id']) or not SEMVER.fullmatch(d['version']):raise ValueError('stable Mission id and semantic version required')
    if type(d['revision']) is not int or d['revision']<0:raise ValueError('draft revision required')
    if type(d['name']) is not str or not 1<=len(d['name'])<=128:raise ValueError('bounded Mission name required')
    if type(d['supported_vehicles']) is not list or not d['supported_vehicles'] or set(d['supported_vehicles'])-{'rover','copter','plane'}:raise ValueError('supported vehicle kinds required')
    if len(json.dumps(d,allow_nan=False).encode())>131072:raise ValueError('Studio definition budget exceeded')
    if type(d['nodes']) is not list or not 1<=len(d['nodes'])<=128 or type(d['edges']) is not list or len(d['edges'])>256:raise ValueError('bounded graph required')
    d.setdefault('blackboard',{});d.setdefault('execution_policy',{});d.setdefault('failure_policy',{'mode':'abort'});d.setdefault('metadata',{});d.setdefault('sub_mission_references',[])
    d.setdefault('interface',dict(inputs={},outputs={}))
    if d['execution_policy'].keys()-{'timeout_s','breakpoints'} or d['failure_policy']!={'mode':'abort'}:raise ValueError('unsupported Mission execution policy')
    bounded_number(d['execution_policy'].setdefault('timeout_s',600),.1,1800,'Mission timeout')
    if type(d['blackboard']) is not dict or len(d['blackboard'])>64:raise ValueError('bounded Blackboard declarations required')
    for name,decl in d['blackboard'].items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',name):raise ValueError('invalid variable name')
        declaration(decl)
    if set(d['interface'])!={'inputs','outputs'}:raise ValueError('explicit SubMission ports required')
    for fields in d['interface'].values():
        if type(fields) is not dict or len(fields)>32:raise ValueError('bounded SubMission ports required')
        for name,decl in fields.items():declaration(decl)
    return d


def compile_graph(document,registry,drivers,*,resolve=None,stack=(),pins=None):
    d=normalize(document);target=d['target']
    if target not in drivers:raise ValueError('unknown vehicle target')
    kind=drivers[target].context().target_kind
    if kind not in d['supported_vehicles']:raise ValueError('Mission does not support selected vehicle')
    identity=d['mission_id']+'@'+d['version']
    if identity in stack or len(stack)>=8:raise ValueError('recursive or excessive SubMission nesting')
    pins={} if pins is None else pins
    variables={'mission.'+k:v for k,v in d['blackboard'].items()}
    variables.update({'submission.'+k:v for k,v in {**d['interface']['inputs'],**d['interface']['outputs']}.items()})
    nodes={};out={};edge_ids=set();incoming={};outputs={};resources=[];compiled=[];used=set();active=set()
    for n in d['nodes']:
        if type(n) is not dict or not NODE_ID.fullmatch(n.get('node_id','')) or n['node_id'] in nodes or n.get('type') not in TYPES:raise ValueError('unique bounded node id/type required')
        if n.keys()-{'node_id','type','name','position','parameters','action_type','action_contract_version','input_bindings','output_bindings','execution_policy','failure_policy','sub_mission','metadata'}:raise ValueError('unknown node fields')
        n.setdefault('parameters',{});n.setdefault('input_bindings',{});n.setdefault('output_bindings',{});n.setdefault('execution_policy',{})
        if any(type(n[k]) is not dict for k in ('parameters','input_bindings','output_bindings','execution_policy')):raise ValueError('typed node configuration objects required')
        if 'position' in n:
            if set(n['position'])!={'x','y'}:raise ValueError('node position x/y required')
            for value in n['position'].values():bounded_number(value,-100000,100000,'layout')
        nodes[n['node_id']]=n;out[n['node_id']]={}
        if type(n.get('metadata',{})) is not dict:raise ValueError('node metadata must be an object')
        if n['type']=='Action':
            entry=registry.resolve_typed(n.get('action_type'),n.get('action_contract_version'));n['action_contract_version']=entry.spec.version
            if entry.spec.vehicle_types and kind not in entry.spec.vehicle_types or not entry.spec.required_capabilities<=drivers[target].context().capabilities:raise ValueError('Action vehicle/capability unavailable')
            if entry.spec.vehicle_types and set(d['supported_vehicles'])-entry.spec.vehicle_types:raise ValueError('Action is incompatible with declared supported vehicles')
            outputs[n['node_id']]=to_json_value(entry.spec.output_schema)
            resources.extend(to_json_value(entry.spec.resources))
    for e in d['edges']:
        if type(e) is not dict or set(e)!={'edge_id','source','target','port'} or not NODE_ID.fullmatch(e['edge_id']) or e['edge_id'] in edge_ids:raise ValueError('unique edge identity required')
        a,b,p=e['source'],e['target'],e['port']
        if a not in nodes or b not in nodes or a==b or p in out[a]:raise ValueError('dangling, duplicate or self edge')
        allowed=TYPES[nodes[a]['type']]['ports']
        if p not in allowed and not any(q.endswith('*') and re.fullmatch(q[:-1]+r'[0-9]{1,2}',p) for q in allowed):raise ValueError('edge uses unsupported output port')
        edge_ids.add(e['edge_id']);out[a][p]=b;incoming.setdefault(b,[]).append(a)
    starts=[n['node_id'] for n in nodes.values() if n['type']=='Start']
    if len(starts)!=1 or not any(n['type']=='End' for n in nodes.values()):raise ValueError('one Start and at least one End required')
    for key,parents in incoming.items():
        if len(parents)>1 and nodes[key]['type']!='Join':raise ValueError('shared control flow must use an explicit Join')
    if incoming.get(starts[0]):raise ValueError('Start cannot have incoming control flow')
    dominators={k:({k} if k==starts[0] else set(nodes)) for k in nodes}
    for _ in range(len(nodes)):
        for k in nodes:
            if k==starts[0]:continue
            parents=incoming.get(k,[]);dominators[k]={k}|(set.intersection(*(dominators[p] for p in parents)) if parents else set())
    def check_binding(key,binding,env):
        ref=binding.get('ref','') if isinstance(binding,dict) else ''
        if ref.startswith('node.'):
            producer=ref.split('.')[1]
            if producer==key or producer not in dominators[key]:raise ValueError('binding must reference a dominating upstream execution')
        return binding_schema(binding,env,outputs)
    def destination(binding,env):
        ref=binding['ref']
        if ref in env and env[ref].get('readonly'):raise ValueError('output binding cannot write read-only external state')
        return binding_schema({'ref':ref},env,outputs)
    def check_expression(key,e,env):
        expression_check(e)
        if e['op'] in ('all','any'):
            for child in e['args']:check_expression(key,child,env)
        elif e['op']=='not':check_expression(key,e['arg'],env)
        else:
            source=check_binding(key,dict(source='world',path=e['path']) if e['source']=='world' else dict(ref=e['path']),env)
            expected={'type':{bool:'boolean',int:'integer',float:'number',str:'string',type(None):'null'}[type(e['value'])]}
            if not compatible(expected,source) and not compatible(source,expected):raise ValueError('typed condition comparison mismatch')
    def emit(node):
        if len(compiled)>=512:raise ValueError('expanded graph node budget exceeded')
        compiled.append(node);return node['id']
    def runtime_id(key,suffix=''):
        return 'b'+hashlib.sha256((identity+'|'+key+'|'+suffix).encode()).hexdigest()[:24]
    def flow(key,stop=None,env=None):
        if key==stop:return emit(dict(id=runtime_id(key,'boundary:'+str(len(compiled))),type='Result',children=[],outcome='SUCCEEDED'))
        if key in active or key in used:raise ValueError('unbounded cycle or unstructured shared branch')
        active.add(key);used.add(key);n=nodes[key];t=n['type'];ports=out[key];env=variables if env is None else env
        policy=n['execution_policy'];rid=runtime_id(key);node=dict(id=rid,type=t,children=[],source_node_id=key)
        policies={'Start':set(),'End':{'outcome'},'Join':set(),'Action':{'skippable','runtime_overrides'},
            'Condition':{'expression'},'Wait':{'mode','expression','event'},'ForEach':{'collection','max_iterations','on_item_failure'},
            'Parallel':{'join_id','max_concurrency','completion','failure'},'Sequence':{'join_id'},'Recovery':{'join_id'},
            'Retry':{'count'},'SubMission':set()}
        if policy.keys()-policies[t]-{'timeout_s'}:raise ValueError('unsupported node execution policy for '+t)
        if 'timeout_s' in policy:bounded_number(policy['timeout_s'],.05,d['execution_policy']['timeout_s'],'node timeout');node['timeout_s']=policy['timeout_s']
        next_key=ports.get('next');join=policy.get('join_id')
        if join is not None:
            if join not in nodes or nodes[join]['type']!='Join' or next_key not in (None,join):raise ValueError('explicit matching Join required')
            next_key=join
        if t in ('Start','Join','End'):
            if t=='Start' and set(ports)!={'next'}:raise ValueError('Start requires next')
            node.update(type='Result',outcome=policy.get('outcome','SUCCEEDED'))
            if node['outcome'] not in ('SUCCEEDED','FAILED','UNKNOWN'):raise ValueError('bounded End outcome required')
        elif t=='Action':
            meta=registry.metadata(n['action_type'],n['action_contract_version'],vehicle_kind=kind);schema=meta['parameters'];params=deepcopy(n['parameters'])
            if params.keys()&n['input_bindings'].keys() or (params.keys()|n['input_bindings'].keys())-schema['properties'].keys():raise ValueError('unknown or multiply bound Action parameter')
            if set(schema.get('required',[]))-(params.keys()|n['input_bindings'].keys()):raise ValueError('missing required Action parameter')
            for field,value in params.items():validate_json(value,schema['properties'][field],field)
            for field,binding in n['input_bindings'].items():
                if not compatible(check_binding(key,binding,env),schema['properties'][field]):raise ValueError('Action binding type mismatch: '+field)
                params[field]={'$binding':deepcopy(binding)}
            if not n['input_bindings']:registry.parameters(n['action_type'],params,n['action_contract_version'],vehicle_kind=kind)
            node.update(action=n['action_type'],action_version=n['action_contract_version'],parameters=params,output_bindings=deepcopy(n['output_bindings']))
            if policy.get('skippable') and not meta['skippable']:raise ValueError('Action contract does not permit skip')
            overrides=policy.get('runtime_overrides',[])
            if type(overrides) is not list or set(overrides)-set(meta['runtime_mutable_parameters']):raise ValueError('Action contract does not permit runtime override')
            node.update(skippable=bool(policy.get('skippable')),runtime_overrides=overrides)
            for field,binding in n['output_bindings'].items():
                if type(binding) is not dict or binding.keys()-{'ref','mode'}:raise ValueError('strict output binding required')
                if len(binding.get('ref','').split('.'))!=2 or binding['ref'].split('.')[0] not in ('mission','submission','local'):raise ValueError('output must target one declared scope variable')
                dest=destination(binding,env)
                if binding.get('mode','set')=='append':dest=dest.get('items',{})
                elif binding.get('mode','set')!='set':raise ValueError('unknown output binding mode')
                if outputs[key] is None:raise ValueError('output bindings require a declared Action output schema')
                source=outputs[key] if field=='result' else subschema(outputs[key],field.split('.'))
                if not compatible(source,dest):raise ValueError('output binding type mismatch')
        elif t=='Wait':
            mode=policy.get('mode','duration')
            if mode=='duration':node['duration_s']=n['parameters'].get('duration_s',1.);bounded_number(node['duration_s'],0,d['execution_policy']['timeout_s'],'Wait')
            elif mode=='condition':node.update(type='Await',expression=policy['expression']);check_expression(key,node['expression'],env)
            elif mode=='event':
                if type(policy.get('event')) is not str or not IDENTITY.fullmatch(policy['event']):raise ValueError('bounded Wait event name required')
                node.update(type='Await',event=policy['event'])
            else:raise ValueError('unknown Wait mode')
        elif t=='Condition':
            node['expression']=policy.get('expression');check_expression(key,node['expression'],env)
            if set(ports)-{'true','false','unknown','next'} or not {'true','false'}<=ports.keys():raise ValueError('Condition requires true/false ports')
            node['children']=[flow(ports[p],join or stop,env) for p in ('true','false','unknown') if p in ports]
        elif t in ('Parallel','Sequence','Recovery','Retry'):
            selected=sorted((p for p in ports if p.startswith('branch:' if t=='Parallel' else 'child:')),key=lambda s:int(s.split(':')[1])) if t in ('Parallel','Sequence') else ['try','recover'] if t=='Recovery' else ['body']
            if not selected or len(selected)>16 or any(p not in ports for p in selected):raise ValueError('bounded declared branches required')
            node['children']=[flow(ports[p],join or stop,env) for p in selected]
            if t=='Parallel':node.update(completion=policy.get('completion','all'),failure=policy.get('failure','fail_fast'),max_concurrency=policy.get('max_concurrency',len(selected)))
            if t=='Retry':node['count']=policy.get('count',2)
        elif t=='ForEach':
            binding=policy.get('collection');schema=check_binding(key,binding,env)
            if schema.get('type')!='array' or 'body' not in ports:raise ValueError('ForEach requires a typed collection and body')
            maximum=policy.get('max_iterations',20)
            if type(maximum) is not int or not 1<=maximum<=20:raise ValueError('ForEach max_iterations=1..20 required')
            local=dict(env,**{'loop.current_item':{'schema':schema['items']},'loop.index':{'schema':{'type':'integer'}},'loop.iteration_id':{'schema':{'type':'string'}}})
            node.update(collection=deepcopy(binding),max_iterations=maximum,item_schema=deepcopy(schema['items']),on_item_failure=policy.get('on_item_failure','abort'))
            if node['on_item_failure'] not in ('abort','continue'):raise ValueError('explicit iteration failure policy required')
            node['children']=[flow(ports['body'],join,local)]
        elif t=='SubMission':
            ref=n.get('sub_mission')
            if type(ref) is not dict or set(ref)!={'mission_id','version'}:raise ValueError('pinned SubMission reference required')
            pin=ref['mission_id']+'@'+ref['version']
            child=pins.get(pin) if pin in pins else None if resolve is None else resolve(ref['mission_id'],ref['version'])
            if child is None:raise ValueError('pinned SubMission publication unavailable')
            child=deepcopy(child);child['target']=target;child=normalize(child);pins[pin]=child
            sub=compile_graph(child,registry,drivers,resolve=resolve,stack=stack+(identity,),pins=pins)
            inputs=child['interface']['inputs'];supplied=set(n['parameters'])|set(n['input_bindings'])
            if supplied-inputs.keys() or any(k not in supplied and 'default' not in v for k,v in inputs.items()):raise ValueError('SubMission input mapping missing or unknown')
            for k,v in n['parameters'].items():validate_json(v,inputs[k]['schema'])
            for k,v in n['input_bindings'].items():
                if not compatible(check_binding(key,v,env),inputs[k]['schema']):raise ValueError('SubMission input type mismatch')
            renames={q['id']:runtime_id(key,q['id']) for q in sub['nodes']}
            for q in sub['nodes']:
                q=deepcopy(q);q['id']=renames[q['id']];q['children']=[renames[c] for c in q['children']];emit(q)
            node.update(children=[renames[sub['root']]],sub_mission=ref,interface=child['interface'],local_definitions=child['blackboard'],
                parameters=deepcopy(n['parameters']),input_bindings=deepcopy(n['input_bindings']),output_bindings=deepcopy(n['output_bindings']))
            node['timeout_s']=min(policy.get('timeout_s',d['execution_policy']['timeout_s']),child['execution_policy']['timeout_s'])
            for field,binding in n['output_bindings'].items():
                if field not in child['interface']['outputs'] or type(binding) is not dict or binding.keys()-{'ref','mode'} or len(binding.get('ref','').split('.'))!=2:raise ValueError('declared SubMission output mapping required')
                dest=destination(binding,env)
                if binding.get('mode','set')=='append':dest=dest.get('items',{})
                elif binding.get('mode','set')!='set':raise ValueError('unknown output binding mode')
                if not compatible(child['interface']['outputs'][field]['schema'],dest):raise ValueError('SubMission output type mismatch')
            for k,v in child['interface']['outputs'].items():outputs[key]=dict(type='object',properties={a:b['schema'] for a,b in child['interface']['outputs'].items()})
        failure=ports.get('failure');failure_policy=n.get('failure_policy',{'mode':'abort'})
        if type(failure_policy) is not dict or failure_policy.keys()-{'mode','attempts'} or failure_policy.get('mode') not in ('abort','branch','retry'):raise ValueError('explicit supported failure policy required')
        if failure_policy['mode']=='branch' and failure is None:raise ValueError('failure branch edge required')
        emit(node);result=rid
        if failure_policy['mode']=='retry':result=emit(dict(id=runtime_id(key,'retry'),type='Retry',source_node_id=key,children=[rid],count=failure_policy.get('attempts',2)))
        if failure:
            result=emit(dict(id=runtime_id(key,'recover'),type='Recovery',source_node_id=key,children=[rid,flow(failure,join or stop,env)]))
        active.remove(key)
        if next_key is not None:result=emit(dict(id=runtime_id(key,'next'),type='Sequence',children=[result,flow(next_key,stop,env)]))
        return result
    root=flow(starts[0])
    if used!=nodes.keys():raise ValueError('unreachable graph nodes')
    if set(d['execution_policy'].get('breakpoints',[]))-nodes.keys():raise ValueError('breakpoint node unavailable')
    declared=sorted({r.name for n in compiled if n['type']=='Action' for r in registry.resolve_typed(n['action'],n['action_version']).spec.resources})
    if 'resource_requirements' in d and sorted(d['resource_requirements'])!=declared:raise ValueError('Mission resource requirements must match registered contracts')
    d['resource_requirements']=declared
    references=sorted({n['sub_mission']['mission_id']+'@'+n['sub_mission']['version'] for n in d['nodes'] if n['type']=='SubMission'})
    if d['sub_mission_references'] and sorted(d['sub_mission_references'])!=references:raise ValueError('SubMission dependency pins do not match graph')
    d['sub_mission_references']=references
    return dict(schema_version=1,id=d['mission_id'],name=d['name'],version=d['version'],target=target,root=root,nodes=compiled,
        blackboard={},timeout_s=d['execution_policy']['timeout_s'],studio=dict(definition=d,definition_hash=digest(d),dependencies=deepcopy(pins)))


def migrate(document,*,registry=None,drivers=None):
    """Explicit copy to schema 2; never edit a historical schema-1 version."""
    d=deepcopy(document)
    if d.get('schema_version')==2:return normalize(d)
    if d.get('schema_version')!=1:raise ValueError('unsupported migration source schema')
    ids={n['id']:'n'+hashlib.sha256(n['id'].encode()).hexdigest()[:12] for n in d['nodes']};nodes=[];edges=[];extra_definitions={}
    def edge(a,b,p):edges.append(dict(edge_id='e'+str(len(edges)),source=a,target=b,port=p))
    for old in d['nodes']:
        n=dict(node_id=ids[old['id']],type=old['type'],parameters=deepcopy(old.get('parameters',{})),execution_policy={})
        if 'position' in old:n['position']=old['position']
        for key in ('timeout_s','expression','completion','failure','event'): 
            if key in old:n['execution_policy'][key]=old[key]
        if old['type']=='Action':
            n.update(action_type=old['action'],action_contract_version=old.get('action_version','1.0.0'));n['input_bindings']={}
            for name,value in list(n['parameters'].items()):
                if type(value) is dict and set(value)=={'$query'}:
                    query=deepcopy(value['$query']);source=query.pop('source');path=query.pop('path')
                    if source not in ('world','blackboard'):raise ValueError('unsupported historical binding source')
                    n['input_bindings'][name]=dict(query,**(dict(source='world',path=path) if source=='world' else dict(ref='mission.'+path)))
                    del n['parameters'][name]
            if 'output' in old:
                if registry is None:raise ValueError('Action output migration needs the registered output schema; historical source remains unchanged')
                schema=to_json_value(registry.resolve_typed(n['action_type'],n['action_contract_version']).spec.output_schema)
                if schema is None:raise ValueError('historical output has no declared schema; explicitly remodel its consumer')
                extra_definitions[old['output']]=dict(schema=schema);n['output_bindings']={'result':dict(ref='mission.'+old['output'])}
        if old['type']=='Wait':n['parameters']['duration_s']=old['duration_s']
        if old['type'] not in TYPES:raise ValueError('legacy '+old['type']+' must remain schema 1 until explicitly remodelled')
        if old['type']=='Condition':
            def scoped(expression):
                if expression.get('op') in ('all','any'):
                    for child in expression['args']:scoped(child)
                elif expression.get('op')=='not':scoped(expression['arg'])
                elif expression.get('source')=='blackboard':expression['path']='mission.'+expression['path']
            scoped(n['execution_policy']['expression'])
            if not old.get('children'):
                for port,outcome in [('true','SUCCEEDED'),('false','FAILED'),('unknown','UNKNOWN')]:
                    child=n['node_id']+'_'+port;nodes.append(dict(node_id=child,type='End',execution_policy={'outcome':outcome}));edge(n['node_id'],child,port)
        for i,c in enumerate(old.get('children',[])):
            port=('true','false','unknown')[i] if old['type']=='Condition' else ('try','recover')[i] if old['type']=='Recovery' else ('branch:' if old['type']=='Parallel' else 'child:')+str(i)
            edge(n['node_id'],ids[c],port)
        nodes.append(n)
    nodes.extend([dict(node_id='start',type='Start'),dict(node_id='end',type='End')]);edge('start',ids[d['root']],'next');edge(ids[d['root']],'end','next')
    def infer(v):
        if type(v) is list:return dict(type='array',items=infer(v[0]) if v else {'type':'string'})
        if type(v) is dict:return dict(type='object',properties={k:infer(x) for k,x in v.items()},required=list(v),additionalProperties=False)
        return dict(type={bool:'boolean',int:'integer',float:'number',str:'string',type(None):'null'}[type(v)])
    board={k:dict(schema=infer(v),default=v) for k,v in d.get('blackboard',{}).items()}
    for name,decl in extra_definitions.items():
        if name in board:decl['default']=board[name]['default']
        board[name]=decl
    kinds=[drivers[d['target']].context().target_kind] if drivers is not None and d['target'] in drivers else ['rover','copter','plane']
    return normalize(dict(schema_version=2,mission_id=d['id'],revision=0,version=d['version'],name=d['name'],target=d['target'],supported_vehicles=kinds,nodes=nodes,edges=edges,
        execution_policy=dict(timeout_s=d.get('timeout_s',600)),blackboard=board,metadata={'migrated_from':1}))
