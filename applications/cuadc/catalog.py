"""Small rewritten CUADC business recipe; competition policy remains in application."""
from actions.basic import BasicParameters
from applications.cuadc.actions import TargetParameters
from contracts.decision import MissionPlan,MissionStep
from core.sitl_mode_action import SITL_MODE_SPEC,SitlModeParameters

NAMES=frozenset({'cuadc_demo','object_inspection'})

def build(name,kind,environment,mode_id,payload_available):
    if name not in NAMES:raise ValueError('unregistered business mission')
    if name=='cuadc_demo' and (kind!='copter' or not payload_available):raise ValueError('explicit Copter simulation payload required')
    steps=[MissionStep('mode',SITL_MODE_SPEC.name,SitlModeParameters('GUIDED',mode_id))]
    def basic(step,action,target=None,timeout=15):
        steps.append(MissionStep(step,'basic.'+action,BasicParameters(kind,environment.reference,None if target is None else environment.resolve(target),timeout_ns=timeout*1_000_000_000)))
    region=next((r for r in environment.regions if r.name=='search'),None)
    if region is None:raise ValueError('named search region required')
    altitude=environment.resolve('HOME_AIR').position.z if kind=='copter' else environment.home().position.z
    basic('arm','arm')
    if kind=='copter':basic('takeoff','takeoff',timeout=30)
    basic('search','goto','A',45)
    steps.append(MissionStep('approach_release' if name=='cuadc_demo' else 'inspect','cuadc.approach_release' if name=='cuadc_demo' else 'cuadc.inspect',
        TargetParameters(kind,environment.reference,region,altitude,'sim_payload_1' if name=='cuadc_demo' else None)))
    basic('home','return_home','HOME_AIR' if kind=='copter' else 'HOME',45)
    if kind=='copter':basic('land','land','HOME',25)
    else:basic('stop','stop',timeout=8)
    basic('disarm','disarm')
    return MissionPlan(name,tuple(steps))
