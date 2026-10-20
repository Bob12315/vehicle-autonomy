"""Finite application-owned mission recipes; no raw coordinates or ports."""
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:  # Ubuntu 22.04 / Python 3.10, isolated dependency
    import tomli as tomllib
from actions.basic import BasicParameters
from contracts.decision import MissionPlan, MissionStep
from core.sitl_mode_action import SITL_MODE_SPEC, SitlModeParameters

MISSION_NAMES = frozenset({'action_probe','safe_recovery','basic_route'})


def capabilities(kind):
    return frozenset({'arm','disarm','navigation','hold','stop'} | ({'takeoff','land'} if kind=='copter' else set()))


def build(name, kind, environment, mode_id):
    if name not in MISSION_NAMES:
        raise ValueError('unregistered mission')
    steps=[]

    def basic(step, action, target=None, timeout=15):
        steps.append(MissionStep(step,'basic.'+action,BasicParameters(kind,environment.reference,
            None if target is None else environment.resolve(target),timeout_ns=timeout*1_000_000_000)))
    if name=='safe_recovery':
        if kind=='copter':basic('land','land','HOME',25)
        else:basic('stop','stop',timeout=8)
        basic('disarm','disarm')
        return MissionPlan(name,tuple(steps))
    home = environment.home()
    if kind == 'copter':
        airborne = environment.resolve('HOME_AIR')
        if (airborne.position.x,airborne.position.y) != (home.position.x,home.position.y):
            raise ValueError('airborne return target does not match configured home')
    steps.append(MissionStep('mode',SITL_MODE_SPEC.name,SitlModeParameters('GUIDED',mode_id)))
    if name=='basic_route':
        path=Path(__file__).resolve().parents[1]/f'simulation/missions/{kind}.toml'
        document=tomllib.loads(path.read_text())
        if set(document)!={'schema','name','vehicle_kind','failure_policy','steps'} or document['schema']!=1 or document['name']!=name or document['vehicle_kind']!=kind or document['failure_policy']!='STOP':
            raise ValueError('invalid route schema')
        for item in document['steps']:
            if set(item)-{'id','action','target','timeout_s'} or not {'id','action','timeout_s'}<=set(item):
                raise ValueError('invalid route step')
            if type(item['timeout_s']) is not int or item['action'] not in ('arm','disarm','takeoff','land','goto','return_home','hold','stop'):
                raise ValueError('unsupported route Action')
            if item['action'] in ('goto','return_home','land') and 'target' not in item:
                raise ValueError('route needs a named target')
            basic(item['id'],item['action'],item.get('target'),item['timeout_s'])
        return MissionPlan(name,tuple(steps))
    basic('arm','arm')
    if kind=='copter':basic('takeoff','takeoff',timeout=30)
    basic('goto_a','goto','A',45)
    basic('hold','hold',timeout=10)
    basic('home','return_home','HOME_AIR' if kind=='copter' else 'HOME',45)
    if kind=='copter':basic('land','land','HOME',25)
    else:basic('stop','stop',timeout=8)
    basic('disarm','disarm')
    return MissionPlan(name,tuple(steps))
