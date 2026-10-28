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
    object_fields(value, required, ('process_names',))
    if value['schema'] != 1: raise ValueError('Tool schema 1 required')
    identifier(value['id']); string(value['name'], 128); string(value['version'], 128)
    if type(value.get('process_names', [])) is not list or len(value.get('process_names', [])) > 16: raise ValueError('bounded process names required')
    for name in value.get('process_names', []): identifier(name)
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
        object_fields(p, ('argv', 'env', 'health', 'ready', 'connection'), ('cwd', 'startup_timeout_s', 'stop_timeout_s', 'requires', 'observe_only','exclusive_ports'))
        argv(p['argv'], empty=p.get('observe_only') is True)
        if type(p.get('observe_only', False)) is not bool: raise ValueError('observe_only must be boolean')
        if p.get('cwd') is not None and not string(p['cwd'], 4096).startswith('/'): raise ValueError('absolute trusted cwd required')
        if type(p['env']) is not dict or len(p['env']) > 128: raise ValueError('bounded environment required')
        for k, v in p['env'].items():
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', k) is None: raise ValueError('invalid environment name')
            string(v, 8192)
        probe(p['health']); probe(p['ready'])
        object_fields(p['connection'], ('kind', 'description'), ('telemetry_only','endpoint'))
        string(p['connection']['kind'], 64); string(p['connection']['description'])
        if 'endpoint' in p['connection']:string(p['connection']['endpoint'])
        if 'telemetry_only' in p['connection'] and type(p['connection']['telemetry_only']) is not bool: raise ValueError('boolean connection policy required')
        number(p.get('startup_timeout_s', 20), .2, 180); number(p.get('stop_timeout_s', 3), .1, 10)
        if type(p.get('exclusive_ports',[])) is not list or len(p.get('exclusive_ports',[]))>8:raise ValueError('bounded exclusive simulation ports required')
        for port in p.get('exclusive_ports',[]):
            object_fields(port,('protocol','port'))
            if port['protocol'] not in ('tcp','udp') or type(port['port']) is not int or not 1024<=port['port']<=65535:raise ValueError('invalid simulation port reservation')
        if type(p.get('requires',[])) is not list or len(p.get('requires',[]))>32:raise ValueError('bounded profile dependencies required')
        for dep in p.get('requires', []):
            object_fields(dep, ('kind', 'value'))
            if dep['kind'] not in ('executable', 'file', 'directory', 'environment'): raise ValueError('invalid profile dependency')
            string(dep['value'], 4096)
            if dep['kind'] in ('file','directory') and not dep['value'].startswith('/'):raise ValueError('absolute trusted dependency path required')
    return deepcopy(value)


def tool_report(value):
    """Validate the public, redacted Agent wire contract before state mutation."""
    object_fields(value,('manifest','checks','external_pids','instance'))
    m=value['manifest']
    object_fields(m,('schema','id','name','type','version','supported_os','integrations','agent_requirements','permissions','stop_strategy','profiles'))
    if m['schema']!=1 or m['type'] not in ('gui','service','simulation') or m['stop_strategy']!='owned_process_group':raise ValueError('invalid Tool report metadata')
    identifier(m['id']);string(m['name'],128);string(m['version'],128)
    for key in ('supported_os','integrations','agent_requirements','permissions'):
        if type(m[key]) is not list or len(m[key])>32:raise ValueError('bounded Tool metadata required')
        for text in m[key]:string(text,128)
    if set(m['permissions'])-{'desktop','ros_read','ros_service','simulation','telemetry_only'}:raise ValueError('unsupported Tool permissions')
    if type(m['profiles']) is not dict or not 1<=len(m['profiles'])<=16 or type(value['checks']) is not dict or set(value['checks'])!=set(m['profiles']):raise ValueError('complete bounded Profile checks required')
    for name,p in m['profiles'].items():
        identifier(name);object_fields(p,('connection','readiness_probe','observe_only'))
        if type(p['readiness_probe']) is not bool or type(p['observe_only']) is not bool:raise ValueError('boolean Profile policy required')
        object_fields(p['connection'],('kind','description'),('telemetry_only','endpoint'))
        string(p['connection']['kind'],64);string(p['connection']['description'])
        if 'endpoint' in p['connection']:string(p['connection']['endpoint'])
        if 'telemetry_only' in p['connection'] and type(p['connection']['telemetry_only']) is not bool:raise ValueError('boolean relay policy required')
        check=value['checks'][name];object_fields(check,('installed','launchable','missing','desktop'))
        if any(type(check[k]) is not bool for k in ('installed','launchable','desktop')):raise ValueError('boolean dependency status required')
        if type(check['missing']) is not list or len(check['missing'])>128:raise ValueError('bounded dependency report required')
        for missing in check['missing']:string(missing,8192)
    if type(value['external_pids']) is not list or len(value['external_pids'])>16 or any(type(pid) is not int or pid<=0 for pid in value['external_pids']):raise ValueError('bounded external process observations required')
    i=value['instance']
    if i is None:return
    object_fields(i,('tool_id','profile_id','context','instance_id','state','owned','process_running','service_health','ready','connection','error','pid','returncode','cleanup_confirmed','started_at','stopping','logs','resource'))
    if i['tool_id']!=m['id'] or i['profile_id'] not in m['profiles']:raise ValueError('Tool instance identity mismatch')
    identifier(i['instance_id']);context(i['context'])
    if i['state'] not in ('STARTING','RUNNING','READY','STOPPING','STOPPED','FAILED','UNKNOWN'):raise ValueError('invalid Tool process state')
    if any(type(i[k]) is not bool for k in ('owned','ready','cleanup_confirmed','stopping')):raise ValueError('boolean process state required')
    if type(i['process_running']) is not bool and not (i['state']=='UNKNOWN' and i['process_running'] is None):raise ValueError('process running must be boolean or explicitly unknown')
    if i['service_health'] not in ('UNKNOWN','HEALTHY','UNHEALTHY') or i['connection'] not in ('UNKNOWN','CONNECTED','DISCONNECTED'):raise ValueError('invalid health/connection state')
    if i['ready'] and (not i['process_running'] or i['state']!='READY' or i['service_health']=='UNHEALTHY' or i['connection']!='CONNECTED'):raise ValueError('readiness requires a live healthy/unknown service with qualified connection')
    if i['state']=='READY' and not i['ready']:raise ValueError('READY process needs readiness evidence')
    if i['pid'] is not None and (type(i['pid']) is not int or i['pid']<=0):raise ValueError('invalid owned pid')
    if i['returncode'] is not None and type(i['returncode']) is not int:raise ValueError('invalid process result')
    if i['error'] is not None and (type(i['error']) is not str or len(i['error'])>1024):raise ValueError('bounded process error required')
    number(i['started_at'],0,1e12)
    if type(i['logs']) is not list or len(i['logs'])>24 or any(type(line) is not str or len(line)>2048 for line in i['logs']):raise ValueError('bounded process logs required')
    object_fields(i['resource'],('rss_bytes','cpu_time_s','scope'))
    for k in ('rss_bytes','cpu_time_s'):
        if i['resource'][k] is not None:number(i['resource'][k],0,1e18)
    string(i['resource']['scope'],128)
