"""Typed scoped values and provenance; no device access or executable expressions."""
from copy import deepcopy
from dataclasses import dataclass
import json,re
from uuid import uuid4

from vehicle_autonomy.contracts.mission import BlackboardValue
from vehicle_autonomy.contracts.core.primitives import thaw_json
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.engine.action.schema import validate_json
from vehicle_autonomy.world.model.mission_inputs import usable,query,blackboard_query

NAME=re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}')


def schema_check(schema,depth=0):
    if type(schema) is not dict or depth>12:raise ValueError('bounded declared data type required')
    if '$ref' in schema or schema.get('type') not in (None,'null','boolean','integer','number','string','array','object'):raise ValueError('unsupported data type; no executable or remote schema references')
    if not any(k in schema for k in ('type','anyOf','enum','const')):raise ValueError('explicit variable type required')
    if 'anyOf' in schema:
        if type(schema['anyOf']) is not list or not 1<=len(schema['anyOf'])<=8:raise ValueError('bounded type union required')
        for child in schema['anyOf']:schema_check(child,depth+1)
    if schema.get('type')=='array':
        if 'items' not in schema:raise ValueError('collection item type required')
        schema_check(schema['items'],depth+1)
    if schema.get('type')=='object':
        if type(schema.get('properties',{})) is not dict or len(schema.get('properties',{}))>64:raise ValueError('bounded object fields required')
        for child in schema.get('properties',{}).values():schema_check(child,depth+1)
    return schema


def declaration(value):
    if type(value) is not dict or 'schema' not in value or value.keys()-{'schema','default','max_age_s','frame','unit','origin','readonly','description','category'}:raise ValueError('typed variable declaration required')
    if type(value['schema']) is not dict or len(json.dumps(value,allow_nan=False))>16384:raise ValueError('bounded variable schema required')
    schema_check(value['schema'])
    if 'readonly' in value and type(value['readonly']) is not bool:raise ValueError('explicit read-only bool required')
    if type(value.get('max_age_s',1800)) not in (int,float) or not 0<value.get('max_age_s',1800)<=3600:raise ValueError('bounded data validity required')
    if value.get('category') in ('pose','pose_stamped','geographic_coordinate','region','path') and not all(value.get(k) for k in ('frame','unit','origin')):raise ValueError('spatial variable needs frame, unit and origin')
    if value.get('category')=='artifact_reference' and value['schema'].get('type')!='object':raise ValueError('artifact reference must be typed metadata')
    if 'default' in value:validate_json(value['default'],value['schema'],'default')
    return deepcopy(value)


def subschema(schema,parts):
    for part in parts:
        if schema.get('type')=='array' and part.isdecimal():schema=schema.get('items',{})
        elif schema.get('type')=='object':schema=schema.get('properties',{}).get(part,{})
        else:raise ValueError('reference path is not declared')
        if not schema:raise ValueError('reference field is not declared')
    return schema


@dataclass
class Cell:
    declaration:dict
    data:BlackboardValue
    revision:int=1
    producer:str='definition'


class Blackboard:
    def __init__(self,definitions,now,*,emit=None):
        if type(definitions) is not dict or len(definitions)>64 or any(not NAME.fullmatch(k) for k in definitions):raise ValueError('bounded declared Blackboard required')
        self.scopes={};self.cells={};self.outputs={};self.history=[];self.emit=emit or (lambda *_a,**_k:None)
        self.create('mission',None,definitions,now,identifier='mission')

    def create(self,kind,parent,definitions,now,*,identifier=None):
        if len(self.scopes)>=1024:raise ValueError('Blackboard scope budget exhausted')
        sid=identifier or (kind+':'+uuid4().hex)
        if sid in self.scopes or parent is not None and parent not in self.scopes:raise ValueError('unique scope and existing parent required')
        declarations={k:declaration(v) for k,v in definitions.items()}
        self.scopes[sid]=dict(id=sid,kind=kind,parent=parent,declarations=declarations,staged={},closed=False)
        for name,d in declarations.items():
            if 'default' in d:self._set(sid,name,d['default'],now,'definition',internal=True)
        return sid

    def ancestors(self,sid):
        while sid is not None:
            yield sid;sid=self.scopes[sid]['parent']

    def scope(self,sid,kind):
        return next((s for s in self.ancestors(sid) if self.scopes[s]['kind']==kind),None)

    def _event(self,event,**fields):
        if len(self.history)>=4096:raise ValueError('Blackboard history budget exhausted')
        value=dict(sequence=len(self.history)+1,event=event,**fields);self.history.append(value);self.emit(event,**fields)

    def _set(self,sid,name,value,now,producer,*,original=None,internal=False):
        scope=self.scopes[sid];d=scope['declarations'].get(name)
        if d is None or scope['closed']:raise ValueError('write to undeclared or closed scope')
        if d.get('readonly') and not internal:raise ValueError('read-only external state cannot be assigned')
        validate_json(value,d['schema'],name)
        if len(json.dumps(value,allow_nan=False).encode())>16384:raise ValueError('use an Artifact Reference for large data')
        previous=self.cells.get((sid,name));revision=1 if previous is None else previous.revision+1
        data=BlackboardValue(value,now,int(d.get('max_age_s',1800)*1e9),frame=d.get('frame'),source=producer)
        if original is not None:
            if d.get('frame') and original.frame!=d['frame']:raise ValueError('binding frame mismatch')
            data=BlackboardValue(value,original.observed_at,min(data.valid_for_ns,original.valid_for_ns),original.quality,original.frame,original.source)
        self.cells[sid,name]=Cell(d,data,revision,producer)
        self._event('blackboard_written',scope_id=sid,name=name,revision=revision,producer=producer,data=to_json_value(data))
        return data

    def destination(self,sid,ref):
        head,name,*parts=ref.split('.')
        if parts or head not in ('mission','local','submission'):raise ValueError('write requires a declared scope variable')
        target=(self.scope(sid,'submission') or 'mission') if head=='mission' else sid if head=='local' else self.scope(sid,'submission')
        if target is None:raise ValueError('SubMission scope unavailable')
        return target,name

    def write(self,sid,ref,value,now,producer,*,original=None,mode='set'):
        target,name=self.destination(sid,ref)
        branch=self.scope(sid,'parallel')
        if mode=='append':
            old=self.cells.get((target,name))
            prior=None if old is None else old.data
            staged=None if branch is None else self.scopes[branch]['staged'].get(target+'.'+name)
            if staged:prior=self._staged_data(staged)
            if prior is None or type(thaw_json(prior.value)) is not list:raise ValueError('append requires an initialized typed list')
            value=thaw_json(prior.value)+[value]
            if original is None or original.observed_at.elapsed_ns_since(prior.observed_at)>=0:original=prior
        elif mode!='set':raise ValueError('unknown output binding mode')
        if branch and target!=branch:
            s=self.scopes[branch];d=self.scopes[target]['declarations'][name];validate_json(value,d['schema'],name)
            current=self.cells.get((target,name));s['staged'][target+'.'+name]=dict(target=target,name=name,value=deepcopy(value),now=now,producer=producer,original=original,expected=0 if current is None else current.revision)
            return
        return self._set(target,name,value,now,producer,original=original)

    def commit(self,branches):
        entries=[v for sid in branches for v in self.scopes[sid]['staged'].values()]
        keys=[(v['target'],v['name']) for v in entries]
        if len(set(keys))!=len(keys):raise ValueError('parallel Blackboard write conflict')
        for v in entries:
            old=self.cells.get((v['target'],v['name']))
            if (0 if old is None else old.revision)!=v['expected']:raise ValueError('parallel Blackboard revision conflict')
            validate_json(v['value'],self.scopes[v['target']]['declarations'][v['name']]['schema'])
        for v in entries:self._set(v['target'],v['name'],v['value'],v['now'],v['producer'],original=v['original'])
        for sid in branches:self.scopes[sid]['closed']=True

    def output(self,sid,node_id,value,now,producer,*,original=None):
        data=original or BlackboardValue(value,now,3_000_000_000,source=producer)
        self.outputs[sid,node_id]=BlackboardValue(value,data.observed_at,data.valid_for_ns,data.quality,data.frame,data.source)

    @staticmethod
    def _staged_data(staged):
        data=staged['original']
        return BlackboardValue(staged['value'],staged['now'] if data is None else data.observed_at,
            3_000_000_000 if data is None else data.valid_for_ns,'VALID' if data is None else data.quality,
            None if data is None else data.frame,staged['producer'] if data is None else data.source)

    def read(self,sid,binding,now,world=None):
        if type(binding) is not dict or binding.keys()-{'ref','source','path','frame','max_age_s','offset'}:raise ValueError('strict typed binding required')
        if binding.get('source')=='world':data=query(world,binding['path'])
        else:
            parts=binding['ref'].split('.');head=parts.pop(0)
            if head=='node':
                node=parts.pop(0)
                if parts and parts[0]=='output':parts.pop(0)
                data=next((self.outputs[s,node] for s in self.ancestors(sid) if (s,node) in self.outputs),None)
            else:
                target=(self.scope(sid,'submission') or 'mission') if head=='mission' else sid if head=='local' else self.scope(sid,head)
                if target is None:raise ValueError('reference scope unavailable')
                name=parts.pop(0);cell=self.cells.get((target,name));data=None if cell is None else cell.data
                branch=self.scope(sid,'parallel')
                staged=None if branch is None else self.scopes[branch]['staged'].get(target+'.'+name)
                if staged:data=self._staged_data(staged)
            if data is not None and parts:
                data=blackboard_query({'value':data},'value.'+'.'.join(parts))
        if not usable(data,now,frame=binding.get('frame'),max_age_s=binding.get('max_age_s')):raise ValueError('UNKNOWN or stale Blackboard binding')
        value=thaw_json(data.value)
        if 'offset' in binding:
            if type(value) not in (int,float):raise ValueError('numeric offset requires numeric data')
            value+=binding['offset']
        return value,data

    def snapshot(self,now):
        return dict(scopes=[{k:deepcopy(v) for k,v in s.items() if k!='staged'} for s in self.scopes.values()],
            values=[dict(scope_id=s,name=n,schema=deepcopy(c.declaration),data=to_json_value(c.data),revision=c.revision,
                producer=c.producer,valid=usable(c.data,now)) for (s,n),c in self.cells.items()],history=deepcopy(self.history))
