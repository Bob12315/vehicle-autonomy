"""Finite application-owned mission recipes; no raw coordinates or ports."""
from actions.basic import BasicParameters
from contracts.decision import MissionPlan, MissionStep
from core.sitl_mode_action import SITL_MODE_SPEC, SitlModeParameters

MISSION_NAMES = frozenset({'action_probe','safe_recovery'})


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
    basic('arm','arm')
    if kind=='copter':basic('takeoff','takeoff',timeout=30)
    basic('goto_a','goto','A',45)
    basic('hold','hold',timeout=10)
    basic('home','return_home','HOME_AIR' if kind=='copter' else 'HOME',45)
    if kind=='copter':basic('land','land','HOME',25)
    else:basic('stop','stop',timeout=8)
    basic('disarm','disarm')
    return MissionPlan(name,tuple(steps))
