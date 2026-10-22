"""Untrusted task designs: immutable, finite references to registered missions."""
from dataclasses import dataclass
import hashlib
import json
import math

MAX_STEPS = 8


def strict_json(content):
    if type(content) is not str or len(content.encode()) > 16384:
        raise ValueError('task design exceeds 16 KiB')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate design field: '+key)
            result[key] = value
        return result
    try:
        return json.loads(content, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('finite JSON required')))
    except RecursionError as exc:
        raise ValueError('design nesting exceeds bounds') from exc


@dataclass(frozen=True, slots=True)
class MissionDesign:
    decision: str
    title: str
    reason: str
    missions: tuple[str, ...]
    arguments: tuple[tuple[tuple[str, object], ...], ...] = ()
    schema: int = 1

    @classmethod
    def parse(cls, content, registered):
        value = strict_json(content)
        if (type(value) is not dict or set(value) != {'schema','decision','title','reason','steps'}
                or type(value['schema']) is not int or value['schema'] not in (1,2)):
            raise ValueError('strict task design schema 1 or 2 required')
        if value['decision'] not in ('propose','clarify','reject'):
            raise ValueError('unknown task design decision')
        if (type(value['title']) is not str or not 1 <= len(value['title']) <= 120
                or type(value['reason']) is not str or not 1 <= len(value['reason']) <= 1000):
            raise ValueError('bounded design title/reason required')
        steps = value['steps']
        if type(steps) is not list or len(steps) > MAX_STEPS:
            raise ValueError('design requires at most eight steps')
        missions = []
        arguments = []
        for step in steps:
            fields={'mission'} if value['schema']==1 else {'mission','parameters'}
            if (type(step) is not dict or set(step) != fields
                    or type(step['mission']) is not str or step['mission'] not in registered
                    or step['mission'].startswith('designed:')):
                raise ValueError('design steps must reference registered, non-nested mission capabilities')
            missions.append(step['mission'])
            parameters={} if value['schema']==1 else step['parameters']
            spec=registered[step['mission']].get('parameters',{}) if isinstance(registered,dict) else {}
            if type(parameters) is not dict or set(parameters)!=set(spec):
                raise ValueError('exact registered mission parameters required')
            for name,rule in spec.items():
                v=parameters[name]
                if 'enum' in rule:
                    if type(v) is not str or v not in rule['enum']:raise ValueError('unknown parameter choice: '+name)
                elif (type(v) not in ((int,) if rule.get('type')=='integer' else (int,float))
                      or not math.isfinite(v) or not rule['min']<=v<=rule['max']):
                    raise ValueError('parameter outside registered bounds: '+name)
            arguments.append(tuple(sorted(parameters.items())))
        if (value['decision'] == 'propose') != bool(missions):
            raise ValueError('only proposals have one to eight executable steps')
        return cls(value['decision'], value['title'], value['reason'], tuple(missions),tuple(arguments),value['schema'])

    def document(self):
        steps=[{'mission':m,**({'parameters':dict(self.arguments[i])} if self.schema==2 else {})}
               for i,m in enumerate(self.missions)]
        return {'schema':self.schema, 'decision':self.decision, 'title':self.title, 'reason':self.reason,'steps':steps}

    @property
    def sha256(self):
        return hashlib.sha256(json.dumps(self.document(), sort_keys=True,
            ensure_ascii=False, separators=(',',':')).encode()).hexdigest()
