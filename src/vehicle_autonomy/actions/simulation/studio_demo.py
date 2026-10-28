"""Deterministic software scene Actions for testing graph semantics.

These Actions never emit Effects. Their geometry comes from a declared software
scene, not images or a real detector, and their outcomes are never physical ACKs.
"""
from dataclasses import dataclass,asdict
from vehicle_autonomy.contracts.action import ActionKind
from vehicle_autonomy.contracts.decision import ActionSpec,ActionDecision,ActionOutcome,ExitDecision


TARGET=dict(type='object',properties=dict(id={'type':'string'},physical_diameter_m={'type':'number'},
    physical_size_source={'type':'string'},bbox_area_px={'type':'integer'},valid={'type':'boolean'},lose_on_confirmation={'type':'boolean'}),
    required=['id','physical_diameter_m','physical_size_source','bbox_area_px','valid','lose_on_confirmation'],additionalProperties=False)
TASK_RESULT=dict(type='object',properties=dict(target_id={'type':'string'},slot={'type':'integer'},status={'type':'string'},
    simulation={'type':'boolean'},physical_action_confirmed={'type':'boolean'}),
    required=['target_id','slot','status','simulation','physical_action_confirmed'],additionalProperties=False)


@dataclass(frozen=True)
class Empty:pass


@dataclass(frozen=True)
class Scene:
    simulate_target_loss:bool=False


@dataclass(frozen=True)
class Target:
    id:str
    physical_diameter_m:float
    physical_size_source:str
    bbox_area_px:int
    valid:bool
    lose_on_confirmation:bool


@dataclass(frozen=True)
class Selection:
    detections:tuple[Target,...]


@dataclass(frozen=True)
class Operation:
    target:Target
    simulated_payload_slot:int
    remaining:int
    def __post_init__(self):
        if self.simulated_payload_slot not in (0,1) or not 0<=self.remaining<=2:raise ValueError('bounded software inventory/slot required')


def output(**properties):return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)


class DemoFactory:
    def __init__(self,operation):self.operation=operation
    def validate_context(self,p,w,c):
        if not c.owned_simulation or c.target_kind!='copter':raise ValueError('software demo requires explicit owned Copter simulation context')
    def start(self,p,w):raise ValueError('explicit simulation context required')
    def start_with_context(self,p,w,c):self.validate_context(p,w,c);return DemoInstance(self.operation,p)


class DemoInstance:
    def __init__(self,operation,p):self.operation=operation;self.p=p
    def tick(self,world):
        p=self.p;op=self.operation
        if op=='PreflightCheck':value=dict(mission_status='SOFTWARE_SIMULATION_READY',simulation=True)
        elif op=='ObserveArea':value=dict(near_m=30.,far_m=35.,source='declared_software_scene',physical_observation_confirmed=False)
        elif op=='DetectContainers':
            value=dict(detections=[dict(id=i,physical_diameter_m=d,physical_size_source='declared_software_scene_geometry',bbox_area_px=pixels,
                valid=True,lose_on_confirmation=p.simulate_target_loss and i=='T-02') for i,d,pixels in [('T-01',.5,100),('T-02',.2,900),('T-03',.35,400)]])
        elif op=='SelectTargets':
            trusted=[t for t in p.detections if t.valid and t.physical_size_source=='declared_software_scene_geometry' and 0<t.physical_diameter_m<=2]
            selected=sorted(trusted,key=lambda t:(t.physical_diameter_m,t.id))[:2]
            value=dict(selected_targets=[asdict(t) for t in selected],count=len(selected))
        elif op=='ConfirmTarget':
            if p.target.lose_on_confirmation:return ActionDecision(ActionOutcome.FAILED,error='simulated_target_lost_at_confirmation')
            value=dict(target=asdict(p.target),confirmed=True)
        elif op in ('SimulatedTaskOperation','RecoverLostTarget'):
            recovered=op=='RecoverLostTarget'
            if not recovered and p.remaining<1:return ActionDecision(ActionOutcome.FAILED,error='software_inventory_empty')
            status='RECOVERED_TARGET_LOST' if recovered else 'SIMULATED_OPERATION_COMPLETE'
            value=dict(operation_status=status,task_result=dict(target_id=p.target.id,slot=p.simulated_payload_slot,status=status,
                simulation=True,physical_action_confirmed=False),current_target=asdict(p.target),remaining=p.remaining if recovered else p.remaining-1)
        elif op=='ReturnAndLand':value=dict(mission_status='SOFTWARE_SIMULATION_COMPLETE',physical_action_confirmed=False)
        else:raise ValueError('unknown software scene operation')
        return ActionDecision(ActionOutcome.SUCCEEDED,result=value)
    def exit(self,world,reason):return ExitDecision(True)


def register_demo(registry):
    operations=[('PreflightCheck',Empty,output(mission_status={'type':'string'},simulation={'type':'boolean'})),
        ('ObserveArea',Empty,output(near_m={'type':'number'},far_m={'type':'number'},source={'type':'string'},physical_observation_confirmed={'type':'boolean'})),
        ('DetectContainers',Scene,output(detections={'type':'array','items':TARGET})),
        ('SelectTargets',Selection,output(selected_targets={'type':'array','items':TARGET},count={'type':'integer'})),
        ('ConfirmTarget',Operation,output(target=TARGET,confirmed={'type':'boolean'})),
        *[(name,Operation,output(operation_status={'type':'string'},task_result=TASK_RESULT,current_target=TARGET,remaining={'type':'integer'})) for name in ('SimulatedTaskOperation','RecoverLostTarget')],
        ('ReturnAndLand',Empty,output(mission_status={'type':'string'},physical_action_confirmed={'type':'boolean'}))]
    for name,parameters,schema in operations:
        registry.register_typed(ActionSpec('Sim.'+name,parameters,kind=ActionKind.GOAL if name=='SimulatedTaskOperation' else ActionKind.QUERY,
            vehicle_types=frozenset({'copter'}),output_schema=schema,external_lifecycle='typed_only',retryable=name!='SimulatedTaskOperation',skippable=False,
            description='Software-only scene: '+name+'. No vehicle/payload Effect, real perception, flight, or physical confirmation.'),DemoFactory(name))
