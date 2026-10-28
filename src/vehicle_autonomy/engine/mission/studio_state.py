"""Per-run scoped data, node execution records and binding helpers.

This is state owned by MissionGraphRuntime, not another scheduler or vehicle port.
"""
from copy import deepcopy
from datetime import datetime
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.core.primitives import thaw_json
from vehicle_autonomy.contracts.mission import BlackboardValue
from .blackboard import Blackboard


def timestamp(value):return TimePoint(value['monotonic_ns'],datetime.fromisoformat(value['utc']),value['clock_domain_id'])


class StudioState:
    def __init__(self,engine,run,now):
        self.engine=engine;self.run=run;self.definition=run.spec['studio']['definition']
        self.board=Blackboard(self.definition['blackboard'],now,emit=lambda event,**kw:engine._event(run,event,**kw))
        self.scopes={k:'mission' for k in run.nodes};self.archived=[]
        self.pause_requested=False;self.breakpoints=set(self.definition['execution_policy'].get('breakpoints',[]));self.bypass=set();self.step_remaining=None;self.overrides={}
        driver=engine.actions.drivers[run.spec['target']];world=driver.snapshot();info=driver.info() if callable(getattr(driver,'info',None)) else {}
        self.vehicle_epoch=(info.get('session_id'),str(getattr(getattr(world,'version',None),'generation_id',None)))

    def context(self,key):return self.scopes.get(key,'mission')

    def assign(self,key,scope):
        self.scopes[key]=scope
        for child in self.run.nodes[key]['children']:self.assign(child,scope)

    def record(self,n):
        spec=self.run.nodes[n.id]
        return dict(node_id=spec.get('source_node_id'),runtime_node_id=n.id,execution_id=n.execution_id,state=n.state,
            scope_id=self.context(n.id),action_id=n.action_id,started_ns=n.started_ns,iteration=n.index,truth=n.truth,
            inputs=deepcopy(n.inputs),outputs=deepcopy(n.outputs),details=deepcopy(n.details))

    def archive(self,n):
        if n.started_ns is None:return
        if len(self.archived)>=4096:raise ValueError('node execution history budget exhausted')
        self.archived.append(self.record(n))

    def resolve(self,parameters,key,world,now):
        result={};snapshots={}
        for name,value in parameters.items():
            if type(value) is dict and set(value)=={'$binding'}:
                value,data=self.board.read(self.context(key),value['$binding'],now,world)
                snapshots[name]=to_json_value(data)
            else:snapshots[name]=dict(value=deepcopy(value),source='fixed')
            result[name]=value
        self.run.runs[key].inputs=snapshots
        self.run.runs[key].details['resolved_parameters']=deepcopy(result)
        return result

    def action_result(self,key,a,now):
        spec=self.run.nodes[key];n=self.run.runs[key];value=a.get('result');stamp=a.get('result_at')
        if value is not None and stamp is None:raise ValueError('Action result has no original timestamp')
        observed=now if stamp is None else timestamp(stamp)
        data=BlackboardValue(value,observed,3_000_000_000,source=a['id'])
        logical=spec['source_node_id'];scope=self.context(key)
        self.board.output(scope,logical,value,now,a['id'],original=data)
        n.outputs=dict(result=deepcopy(value),source=a['id'],observed_at=to_json_value(observed))
        for field,binding in spec.get('output_bindings',{}).items():
            ref='node.'+logical+'.output'+('' if field=='result' else '.'+field)
            value,original=self.board.read(scope,dict(ref=ref),now)
            self.board.write(scope,binding['ref'],value,now,a['id'],original=original,mode=binding.get('mode','set'))

    def foreach_scope(self,key,now):
        n=self.run.runs[key];spec=self.run.nodes[key];parent=self.context(key)
        if 'items' not in n.details:
            world=self.engine.actions.drivers[self.run.spec['target']].snapshot()
            items,data=self.board.read(parent,spec['collection'],now,world)
            if type(items) is not list or len(items)>spec['max_iterations']:raise ValueError('ForEach collection exceeds published iteration budget')
            n.details.update(items=deepcopy(items),source_data=data,iteration_scopes=[])
            n.inputs=dict(collection=to_json_value(data))
        items=n.details['items']
        if n.index>=len(items):return False
        if len(n.details['iteration_scopes'])<=n.index:
            definitions=dict(index=dict(schema={'type':'integer'},default=n.index),iteration_id=dict(schema={'type':'string'},default=n.execution_id+':'+str(n.index)),
                current_item=dict(schema=spec['item_schema'],max_age_s=n.details['source_data'].valid_for_ns/1e9))
            scope=self.board.create('loop',parent,definitions,now)
            self.board._set(scope,'current_item',items[n.index],now,'loop:'+n.execution_id,original=n.details['source_data'],internal=True)
            n.details['iteration_scopes'].append(scope)
            self.assign(spec['children'][0],scope)
            self.engine._event(self.run,'iteration_started',node_id=spec['source_node_id'],execution_id=n.execution_id,index=n.index,scope_id=scope)
        return True

    def submission_enter(self,key,now):
        n=self.run.runs[key];spec=self.run.nodes[key]
        if 'child_scope' in n.details:return
        definitions={**deepcopy(spec['local_definitions']),**deepcopy(spec['interface']['inputs']),**deepcopy(spec['interface']['outputs'])}
        if len(definitions)!=len(spec['local_definitions'])+len(spec['interface']['inputs'])+len(spec['interface']['outputs']):raise ValueError('SubMission variable/port name collision')
        parent=self.context(key);scope=self.board.create('submission',parent,definitions,now)
        for name,value in spec['parameters'].items():self.board._set(scope,name,value,now,'submission:fixed',internal=True)
        world=self.engine.actions.drivers[self.run.spec['target']].snapshot()
        for name,binding in spec['input_bindings'].items():
            value,data=self.board.read(parent,binding,now,world)
            self.board._set(scope,name,value,now,'submission:input',original=data,internal=True)
            n.inputs[name]=to_json_value(data)
        n.details['child_scope']=scope;self.assign(spec['children'][0],scope)
        self.engine._event(self.run,'submission_entered',node_id=spec['source_node_id'],execution_id=n.execution_id,scope_id=scope,reference=spec['sub_mission'])

    def submission_exit(self,key,now):
        n=self.run.runs[key];spec=self.run.nodes[key];scope=n.details['child_scope'];parent=self.context(key)
        samples=[]
        for name in spec['interface']['outputs']:
            value,data=self.board.read(scope,dict(ref='submission.'+name),now)
            samples.append(data)
            n.outputs[name]=to_json_value(data)
            binding=spec.get('output_bindings',{}).get(name)
            if binding:self.board.write(parent,binding['ref'],value,now,'submission:'+n.execution_id,original=data,mode=binding.get('mode','set'))
        result={name:thaw_json(self.board.cells[scope,name].data.value) for name in spec['interface']['outputs']}
        original=None
        if samples:
            oldest=min(samples,key=lambda d:d.observed_at.monotonic_ns)
            # The aggregate may be older than any individual port; it may never
            # become younger just because the child scope completed.
            for sample in samples:sample.observed_at.elapsed_ns_since(oldest.observed_at)
            original=BlackboardValue(result,oldest.observed_at,min(d.valid_for_ns for d in samples),
                frame=oldest.frame if all(d.frame==oldest.frame for d in samples) else None,source='submission:'+n.execution_id)
        self.board.output(parent,spec['source_node_id'],result,now,'submission:'+n.execution_id,original=original)
        self.board.scopes[scope]['closed']=True
        self.engine._event(self.run,'submission_completed',node_id=spec['source_node_id'],execution_id=n.execution_id,scope_id=scope)

    def safe_boundary(self):
        return all(self.engine._action_safe(self.engine.actions.assess(i)) for i in self.run.actions)

    def gate(self,key):
        spec=self.run.nodes[key];logical=spec.get('source_node_id');n=self.run.runs[key]
        if spec['type'] not in ('Action','Wait','Await','ForEach','SubMission','Result') or logical is None:return False
        token=n.execution_id
        if logical in self.breakpoints and token not in self.bypass:
            self.pause_requested=True;self.bypass.add(token)
            self.engine._event(self.run,'breakpoint_reached',node_id=logical,execution_id=token)
        if self.pause_requested and self.safe_boundary():return True
        if self.step_remaining is not None:
            if self.step_remaining<=0 and self.safe_boundary():self.pause_requested=True;return True
            if spec['type'] in ('Action','Wait','Await'):self.step_remaining-=1
        return False

    def snapshot(self,now):
        records=self.archived+[self.record(n) for n in self.run.runs.values() if n.started_ns is not None]
        # BlackboardValue instances in live iteration state are rendered by the
        # shared serializer; no original time/quality is replaced with now.
        return to_json_value(dict(definition=self.definition,definition_hash=self.run.spec['studio']['definition_hash'],
            executions=records,blackboard=self.board.snapshot(now),pause_requested=self.pause_requested,
            breakpoints=sorted(self.breakpoints),overrides=self.overrides))
