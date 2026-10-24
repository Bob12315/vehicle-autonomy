"""Small strict JSON schema codec for immutable, typed Action parameters."""
from __future__ import annotations

from dataclasses import MISSING, fields, is_dataclass
from enum import Enum
import math
from types import UnionType
from typing import Literal, Union, get_args, get_origin, get_type_hints

from vehicle_autonomy.contracts.core.serialization import to_json_value


def type_schema(kind):
    origin, args = get_origin(kind), get_args(kind)
    if origin in (Union, UnionType):return {'anyOf':[type_schema(t) for t in args]}
    if origin is Literal:return {'enum':list(args)}
    if origin in (tuple, frozenset):
        if len(args)==2 and args[1] is Ellipsis:return {'type':'array','items':type_schema(args[0])}
        if origin is frozenset:return {'type':'array','items':type_schema(args[0]),'uniqueItems':True}
        return {'type':'array','prefixItems':[type_schema(t) for t in args],'minItems':len(args),'maxItems':len(args)}
    if kind is type(None):return {'type':'null'}
    if isinstance(kind,type) and issubclass(kind,Enum):return {'enum':[v.value for v in kind]}
    if isinstance(kind,type) and is_dataclass(kind):return parameter_schema(kind)
    if kind in (bool,int,float,str):return {'type':{bool:'boolean',int:'integer',float:'number',str:'string'}[kind]}
    if isinstance(kind,type) and issubclass(kind,str):return {'type':'string','minLength':1}
    raise TypeError(f'unsupported Action schema type: {kind!r}')


def parameter_schema(parameters_type):
    hints=get_type_hints(parameters_type);props={};required=[]
    for f in fields(parameters_type):
        props[f.name]={**type_schema(hints[f.name]),**dict(f.metadata)}
        if f.default is not MISSING:props[f.name]['default']=to_json_value(f.default)
        elif f.default_factory is not MISSING:props[f.name]['default']=to_json_value(f.default_factory())
        else:required.append(f.name)
    return {'type':'object','additionalProperties':False,'properties':props,'required':required}


def validate_json(value,schema,path='parameters'):
    if not isinstance(schema,dict):raise TypeError('schema object required')
    if 'anyOf' in schema:
        for candidate in schema['anyOf']:
            try:validate_json(value,candidate,path);break
            except (ValueError,TypeError):continue
        else:raise ValueError(path+': no declared type matches')
    if 'enum' in schema and not any(type(value) is type(v) and value==v for v in schema['enum']):
        raise ValueError(path+': outside allowed values')
    if 'const' in schema and (type(value) is not type(schema['const']) or value!=schema['const']):
        # JSON numeric equality permits int inputs for a declared float constant.
        if not (type(value) in (int,float) and type(schema['const']) in (int,float) and value==schema['const']):
            raise ValueError(path+': constant mismatch')
    kind=schema.get('type')
    valid={'null':value is None,'boolean':type(value) is bool,'integer':type(value) is int,
           'number':type(value) in (int,float),'string':isinstance(value,str),
           'array':type(value) is list,'object':type(value) is dict}
    if kind and not valid.get(kind,False):raise TypeError(path+': expected '+kind)
    if type(value) in (int,float):
        if not math.isfinite(value):raise ValueError(path+': finite number required')
        for key,good in (('minimum',lambda n:value>=n),('maximum',lambda n:value<=n),
                         ('exclusiveMinimum',lambda n:value>n),('exclusiveMaximum',lambda n:value<n)):
            if key in schema and not good(schema[key]):raise ValueError(path+': '+key+' violated')
    if isinstance(value,str):
        if len(value)<schema.get('minLength',0) or len(value)>schema.get('maxLength',65536):raise ValueError(path+': string length')
    if type(value) is dict:
        props=schema.get('properties',{})
        if schema.get('additionalProperties') is False and value.keys()-props.keys():raise ValueError(path+': unknown fields')
        if set(schema.get('required',()))-value.keys():raise ValueError(path+': missing fields')
        for k,v in value.items():
            if k in props:validate_json(v,props[k],path+'.'+k)
    if type(value) is list:
        if len(value)<schema.get('minItems',0) or len(value)>schema.get('maxItems',4096):raise ValueError(path+': array size')
        if schema.get('uniqueItems') and len({repr(v) for v in value})!=len(value):raise ValueError(path+': duplicate array values')
        for i,v in enumerate(value):
            if 'items' not in schema and 'prefixItems' not in schema:break
            child=schema.get('items') or (schema.get('prefixItems') or [])[i]
            validate_json(v,child,path+f'[{i}]')


def decode(kind,value):
    origin,args=get_origin(kind),get_args(kind)
    if origin in (Union,UnionType):
        for child in args:
            try:validate_json(value,type_schema(child));return decode(child,value)
            except (ValueError,TypeError):continue
        raise ValueError('value does not match Action parameter type')
    if origin is Literal:return value
    if origin in (tuple,frozenset):
        values=(decode(args[0] if origin is frozenset or len(args)==2 and args[1] is Ellipsis else args[i],v)
                for i,v in enumerate(value))
        return frozenset(values) if origin is frozenset else tuple(values)
    if isinstance(kind,type) and is_dataclass(kind):return decode_parameters(kind,value)
    if kind is type(None):return None
    return kind(value)


def decode_parameters(parameters_type,value,schema=None):
    schema=schema or parameter_schema(parameters_type)
    validate_json(value,schema)
    hints=get_type_hints(parameters_type)
    supplied=dict(value)
    for name,prop in schema.get('properties',{}).items():
        if name not in supplied and 'default' in prop:supplied[name]=prop['default']
    validate_json(supplied,schema)
    return parameters_type(**{k:decode(hints[k],v) for k,v in supplied.items()})
