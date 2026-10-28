"""Strict, JSON-compatible Tool/Workspace contracts (no optional ROS imports)."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re


def object_fields(value, required, optional=()):
    if type(value) is not dict or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError('invalid or unknown object fields: ' + ', '.join(required))
    return value


def identifier(value):
    if type(value) is not str or re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}', value) is None:
        raise ValueError('bounded identifier required')
    return value


def string(value, limit=512):
    if type(value) is not str or len(value) > limit or '\0' in value or '\n' in value or '\r' in value:
        raise ValueError('bounded single-line string required')
    return value


def number(value, low, high):
    if type(value) not in (int, float) or not low <= value <= high:
        raise ValueError('finite bounded number required')
    return value


def context(value):
    object_fields(value, ('vehicle_id', 'vehicle_type', 'environment', 'ros_namespace',
                          'ros_domain_id', 'mavlink_profile'), ('workspace_id',))
    identifier(value['vehicle_id'])
    if value['vehicle_type'] not in ('rover', 'copter', 'plane') or value['environment'] not in ('simulation', 'hardware_readonly'):
        raise ValueError('supported vehicle and receive-only hardware context required')
    ns = value['ros_namespace']
    if type(ns) is not str or len(ns) > 128 or re.fullmatch(r'/(?:[A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*)*)?', ns) is None:
        raise ValueError('absolute ROS namespace required')
    if type(value['ros_domain_id']) is not int or not 0 <= value['ros_domain_id'] <= 232:
        raise ValueError('ROS domain must be 0..232')
    identifier(value['mavlink_profile'])
    if 'workspace_id' in value: identifier(value['workspace_id'])
    return deepcopy(value)


def compatibility(value):
    result = context(value)
    result.pop('workspace_id', None)
    return result


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def argv(value, *, empty=False):
    if type(value) is not list or len(value) > 96 or not empty and not value:
        raise ValueError('bounded argv array required')
    for v in value: string(v, 4096)
    if value and (not value[0] or value[0].startswith('-')):
        raise ValueError('executable required')
    return deepcopy(value)


def probe(value):
    if value is None: return None
    object_fields(value, ('argv', 'contains'), ('timeout_s',))
    argv(value['argv'])
    if type(value['contains']) is not list or len(value['contains']) > 32: raise ValueError('bounded probe expectations required')
    for v in value['contains']: string(v, 256)
    number(value.get('timeout_s', 2), .1, 5)
    return deepcopy(value)


def manifest(value):
    required = ('schema', 'id', 'name', 'type', 'version', 'supported_os', 'dependencies',
                'install_detection', 'profiles', 'stop_strategy', 'integrations',
                'agent_requirements', 'permissions')
    object_fields(value, required)
    if value['schema'] != 1: raise ValueError('Tool schema 1 required')
    identifier(value['id']); string(value['name'], 128); string(value['version'], 128)
    if value['type'] not in ('gui', 'service', 'simulation'): raise ValueError('unsupported tool type')
    for key in ('supported_os', 'integrations', 'agent_requirements'):
        if type(value[key]) is not list or len(value[key]) > 32: raise ValueError('bounded metadata lists required')
        for v in value[key]: string(v, 128)
    if value['stop_strategy'] != 'owned_process_group': raise ValueError('only owned process groups may be stopped')
    if type(value['permissions']) is not list or set(value['permissions']) - {'desktop', 'ros_read', 'ros_service', 'simulation', 'telemetry_only'}:
        raise ValueError('unsupported permissions; vehicle command permission does not exist')
    for key in ('dependencies', 'install_detection'):
        if type(value[key]) is not list or len(value[key]) > 32: raise ValueError('bounded dependencies required')
        for dep in value[key]:
            object_fields(dep, ('kind', 'value'))
            if dep['kind'] not in ('executable', 'file', 'directory', 'environment'): raise ValueError('invalid dependency kind')
            string(dep['value'], 4096)
            if dep['kind'] in ('file', 'directory') and not dep['value'].startswith('/'):
                raise ValueError('trusted dependency paths must be absolute')
    profiles = value['profiles']
    if type(profiles) is not dict or not 1 <= len(profiles) <= 16: raise ValueError('1..16 profiles required')
    for name, p in profiles.items():
        identifier(name)
        object_fields(p, ('argv', 'env', 'health', 'ready', 'connection'), ('cwd', 'startup_timeout_s', 'stop_timeout_s', 'requires', 'observe_only'))
        argv(p['argv'], empty=p.get('observe_only') is True)
        if type(p.get('observe_only', False)) is not bool: raise ValueError('observe_only must be boolean')
        if p.get('cwd') is not None and not string(p['cwd'], 4096).startswith('/'): raise ValueError('absolute trusted cwd required')
        if type(p['env']) is not dict or len(p['env']) > 128: raise ValueError('bounded environment required')
        for k, v in p['env'].items():
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', k) is None: raise ValueError('invalid environment name')
            string(v, 8192)
        probe(p['health']); probe(p['ready'])
        object_fields(p['connection'], ('kind', 'description'), ('telemetry_only',))
        string(p['connection']['kind'], 64); string(p['connection']['description'])
        if 'telemetry_only' in p['connection'] and type(p['connection']['telemetry_only']) is not bool: raise ValueError('boolean connection policy required')
        number(p.get('startup_timeout_s', 20), .2, 180); number(p.get('stop_timeout_s', 3), .1, 10)
        for dep in p.get('requires', []):
            object_fields(dep, ('kind', 'value'))
            if dep['kind'] not in ('executable', 'file', 'directory', 'environment'): raise ValueError('invalid profile dependency')
            string(dep['value'], 4096)
    return deepcopy(value)
