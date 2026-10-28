"""Extract a closed linear Action/Wait selection with explicit typed ports."""
from copy import deepcopy
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.engine.mission.studio_graph import binding_schema


def extract(definition,selected,identifier,name,registry):
    d=deepcopy(definition);selected=set(selected);nodes={n['node_id']:n for n in d['nodes']}
    if not 1<=len(selected)<=16 or selected-nodes.keys() or any(nodes[k]['type'] not in ('Action','Wait') for k in selected):raise ValueError('V1 extraction requires 1..16 linear Action/Wait nodes; complex graphs can be authored as independent SubMissions')
    entering=[e for e in d['edges'] if e['target'] in selected and e['source'] not in selected]
    leaving=[e for e in d['edges'] if e['source'] in selected and e['target'] not in selected]
    internal=[e for e in d['edges'] if e['source'] in selected and e['target'] in selected]
    if len(entering)!=1 or len(leaving)!=1 or len(internal)!=len(selected)-1 or any(e['port']!='next' for e in internal+leaving):raise ValueError('selection needs one incoming edge, one next exit and closed linear flow')
    variables={'mission.'+k:v for k,v in d['blackboard'].items()}
    variables.update({'submission.'+k:v for k,v in {**d['interface']['inputs'],**d['interface']['outputs']}.items()})
    variables.update({'loop.index':dict(schema={'type':'integer'}),'loop.iteration_id':dict(schema={'type':'string'})})
    for loop in (n for n in d['nodes'] if n['type']=='ForEach'):
        body=next((e['target'] for e in d['edges'] if e['source']==loop['node_id'] and e['port']=='body'),None)
        reachable=set();queue=[body]
        while queue:
            key=queue.pop()
            if key in reachable:continue
            reachable.add(key);queue.extend(e['target'] for e in d['edges'] if e['source']==key)
        if selected<=reachable:variables['loop.current_item']=dict(schema=binding_schema(loop['execution_policy']['collection'],variables,{})['items'])
    outputs={n['node_id']:to_json_value(registry.resolve_typed(n['action_type'],n['action_contract_version']).spec.output_schema) for n in d['nodes'] if n['type']=='Action'}
    inputs={};exported={};parent_inputs={};parent_outputs={};writes={}
    for key in selected:
        for field,binding in nodes[key]['output_bindings'].items():
            ref=binding['ref']
            if ref in writes:raise ValueError('multiple writes to one external variable need a manually defined SubMission interface')
            writes[ref]=(key,field,binding)
    child_nodes=[deepcopy(n) for n in d['nodes'] if n['node_id'] in selected]
    for n in child_nodes:
        for field,binding in n['input_bindings'].items():
            ref=binding.get('ref','')
            if ref.startswith('node.') and ref.split('.')[1] in selected:continue
            if any(ref==target or ref.startswith(target+'.') for target in writes):raise ValueError('mutable external reads/writes require an explicit SubMission interface')
            port='input_'+str(len(inputs)+1);schema=binding_schema(binding,variables,outputs)
            decl=dict(schema=deepcopy(schema),max_age_s=binding.get('max_age_s',120))
            if binding.get('frame'):decl['frame']=binding['frame']
            inputs[port]=decl;parent_inputs[port]=deepcopy(binding);n['input_bindings'][field]={'ref':'submission.'+port}
        for field,binding in n['output_bindings'].items():
            port='output_'+str(len(exported)+1);schema=outputs[n['node_id']] if field=='result' else outputs[n['node_id']]['properties'][field]
            exported[port]=dict(schema=deepcopy(schema),max_age_s=120);parent_outputs[port]=deepcopy(binding)
            n['output_bindings'][field]={'ref':'submission.'+port}
    # Export whole upstream results when later nodes consume a selected node.
    # Keep those references explicit rather than silently binding an old ID.
    outside=[n for n in d['nodes'] if n['node_id'] not in selected]
    result_ports={}
    replacement='sub_'+identifier[:50]
    def rewrite(value):
        if isinstance(value,dict):
            for key,item in list(value.items()):
                if key in ('ref','path') and isinstance(item,str) and item.startswith('node.') and len(item.split('.'))>=3 and item.split('.')[1] in selected:
                    parts=item.split('.');producer=parts[1]
                    if producer not in result_ports:
                        source=next(n for n in child_nodes if n['node_id']==producer)
                        existing=source['output_bindings'].get('result')
                        port=existing['ref'].split('.')[1] if existing else 'output_'+str(len(exported)+1)
                        if not existing:
                            exported[port]=dict(schema=deepcopy(outputs[producer]),max_age_s=120);source['output_bindings']['result']={'ref':'submission.'+port}
                        result_ports[producer]=port
                    value[key]='node.'+replacement+'.output.'+result_ports[producer]+('.'+'.'.join(parts[3:]) if len(parts)>3 else '')
                else:rewrite(item)
        elif isinstance(value,list):
            for item in value:rewrite(item)
    for n in outside:rewrite(n)
    if len(inputs)>32 or len(exported)>32:raise ValueError('extracted interface exceeds 32-port bound')
    start='extracted_start';end='extracted_end'
    if start in selected or end in selected:raise ValueError('reserved extraction node ID occupied')
    child=dict(schema_version=2,mission_id=identifier,revision=0,version='1.0.0',name=name,target=d['target'],supported_vehicles=deepcopy(d['supported_vehicles']),
        nodes=[dict(node_id=start,type='Start'),*child_nodes,dict(node_id=end,type='End')],
        edges=[dict(edge_id='extracted_entry',source=start,target=entering[0]['target'],port='next'),*internal,
            dict(edge_id='extracted_exit',source=leaving[0]['source'],target=end,port='next')],blackboard={},interface=dict(inputs=inputs,outputs=exported),
        execution_policy=dict(timeout_s=d['execution_policy']['timeout_s'],breakpoints=[k for k in d['execution_policy'].get('breakpoints',[]) if k in selected]),metadata={'extracted_from':d['mission_id']})
    if replacement in nodes:raise ValueError('replacement node ID occupied')
    call=dict(node_id=replacement,type='SubMission',sub_mission=dict(mission_id=identifier,version='1.0.0'),parameters={},input_bindings=parent_inputs,output_bindings=parent_outputs,metadata=deepcopy(nodes[entering[0]['target']].get('metadata',{})))
    call['metadata']['label']=name;d['nodes']=[n for n in d['nodes'] if n['node_id'] not in selected]+[call]
    d['edges']=[e for e in d['edges'] if e['source'] not in selected and e['target'] not in selected]
    d['edges']+=[dict(entering[0],target=replacement),dict(leaving[0],source=replacement,port='next')]
    d['execution_policy']['breakpoints']=[k for k in d['execution_policy'].get('breakpoints',[]) if k not in selected]
    return child,d
