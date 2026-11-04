"""Explicit standard library registration; the same schemas drive API and UI."""
import math

from vehicle_autonomy.actions.common.standard import Empty,ModeParameters,CommonFactory,QueryFactory,ContextFactory,NativeGoal,speed,ground
from vehicle_autonomy.actions.copter.standard import BasicFactory,StreamFactory,TakeoffParameters,GotoParameters,VelocityParameters,YawParameters
from vehicle_autonomy.actions.rover.standard import RoverStreamFactory,DriveParameters,TurnParameters,RoverReturnGoal,RoverStopFactory,RoverGotoFactory
from vehicle_autonomy.actions.plane.standard import PlaneFactory,GuidedTargetParameters
from vehicle_autonomy.contracts.action import ActionKind,ActionResource,ResourceMode
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.decision import ActionSpec
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect,DisarmEffect,ModeEffect,TakeoffEffect,LandEffect,PoseTargetEffect,TwistTargetEffect,StopMotionEffect,FixedWingTargetEffect

KINDS=frozenset({'rover','copter','plane'})
MOTION=(PoseTargetEffect,TwistTargetEffect,StopMotionEffect)


def result_schema(name):
    def object_schema(properties,required=None):
        return {'type':'object','properties':properties,'required':list(properties) if required is None else required,'additionalProperties':False}
    configuration=object_schema({'confirmed':{'type':'string'},'physical_arrival_claim':{'const':False}})
    physical=object_schema({'physical_goal_observed':{'const':True}})
    native=object_schema({'physical_goal_observed':{'const':True},'armed':{'type':'boolean'}})
    if name=='GetVehicleState':
        return object_schema({'target':{'type':'string'},'kind':{'enum':sorted(KINDS)},
            'world':{'type':'object','description':'Immutable WorldSnapshot JSON with source/receive/publish times and quality'},
            'home':{'anyOf':[{'type':'object'},{'type':'null'}]},
            'context':{'anyOf':[{'type':'object'},{'type':'null'}]},'read_only':{'const':True}})
    if name in ('Drive','Turn','SetVelocity','Hold'):return {'type':'null'}
    if name=='SetYaw':return object_schema({'yaw_rad':{'type':'number','minimum':-math.pi,'maximum':math.pi}})
    if name in ('Takeoff','RTL'):return {'anyOf':[physical,native] if name=='Takeoff' else [configuration,native]}
    if name in ('ReturnHome','AutoLand'):return native
    if name in ('Goto','Land','Stop'):return physical
    return configuration


def capabilities(kind):
    common={'state','mode','arm','disarm','rtl'}
    return frozenset(common|({'drive','turn','goto','stop','return_home'} if kind=='rover' else
        {'takeoff','goto','velocity','yaw','hold','return_home','land'} if kind=='copter' else
        {'takeoff','guided_target','loiter','rtl','autoland'} if kind=='plane' else set()))


class TakeoffFactory(ContextFactory):
    def validate_context(self,p,w,c):self.select(c).validate_context(p,w,c)
    def select(self,c):return PlaneFactory('Takeoff') if c.target_kind=='plane' else BasicFactory('takeoff')
    def start_with_context(self,p,w,c):return self.select(c).start_with_context(p,w,c)


class ReturnFactory(ContextFactory):
    def validate_context(self,p,w,c):
        if not w.vehicle.operation.armed or c.home is None:raise ValueError('armed vehicle with explicit home required')
    def start_with_context(self,p,w,c):
        self.validate_context(p,w,c);modes=to_json_value(c.metadata)['mode_ids']
        if 'RTL' not in modes:raise ValueError('native RTL absent from audited profile')
        if c.target_kind=='rover':
            return RoverReturnGoal(modes['RTL'],c.home.position)
        else:
            home=c.home.position
            predicate=lambda s:ground(s,home.z) and not s.vehicle.operation.armed and math.hypot(
                s.vehicle.reported_pose.value.position.x-home.x,s.vehicle.reported_pose.value.position.y-home.y)<=.75
        return NativeGoal('RTL',modes['RTL'],predicate)


class GotoFactory(ContextFactory):
    def select(self,c):return RoverGotoFactory() if c.target_kind=='rover' else BasicFactory('goto')
    def validate_context(self,p,w,c):self.select(c).validate_context(p,w,c)
    def start_with_context(self,p,w,c):return self.select(c).start_with_context(p,w,c)


def register_standard(registry):
    def add(name,p,factory,*,kind=ActionKind.ONE_SHOT,vehicles=KINDS,cap=None,effects=(),resource='vehicle.motion',timeout=30,max_timeout=60,success='',overrides=None,timeouts=None):
        writing=bool(effects)
        registry.register_typed(ActionSpec(name,p,frozenset({cap or name.lower()}),effects,
            1_000_000_000 if any(e in effects for e in (PoseTargetEffect,TwistTargetEffect)) else 5_000_000_000,
            description=name+' using the audited ArduPilot simulation control contract',kind=kind,vehicle_types=vehicles,
            resources=(ActionResource(resource,ResourceMode.EXCLUSIVE,'vehicle.control'),) if writing else
                      (ActionResource('vehicle.state',ResourceMode.SHARED),),
            required_state=('vehicle','reported_pose','reported_twist') if writing else (),
            default_timeout_ns=int(timeout*1e9),max_timeout_ns=int(max_timeout*1e9),exit_timeout_ns=12_000_000_000,
            output_schema=result_schema(name),vehicle_parameter_overrides=overrides,vehicle_timeout_overrides=timeouts,
            effect_ttl_overrides={e.__name__:5_000_000_000 for e in effects if e in (ArmEffect,DisarmEffect,ModeEffect,TakeoffEffect,LandEffect,FixedWingTargetEffect)},
            success_semantics=success,external_lifecycle='typed_only'),factory)
    add('GetVehicleState',Empty,QueryFactory(),kind=ActionKind.QUERY,cap='state',success='Read immutable world, including freshness; grants no authority.')
    for name,p,effect,res in [('SetMode',ModeParameters,ModeEffect,'vehicle.mode'),('Arm',Empty,ArmEffect,'vehicle.arm'),('Disarm',Empty,DisarmEffect,'vehicle.arm')]:
        add(name,p,CommonFactory(name),cap='mode' if name=='SetMode' else name.lower(),effects=(effect,),resource=res,
            overrides={kind:{'mode':{'enum':modes}} for kind,modes in {'rover':['HOLD','GUIDED'],'copter':['GUIDED','LOITER'],
                'plane':['MANUAL','GUIDED','LOITER','RTL']}.items()} if name=='SetMode' else None,
            success='Command COMPLETED plus authenticated post-request target state; mode adoption is not arrival.')
    add('Takeoff',TakeoffParameters,TakeoffFactory(),kind=ActionKind.GOAL,vehicles=frozenset({'copter','plane'}),effects=(TakeoffEffect,ModeEffect,TwistTargetEffect,StopMotionEffect),timeout=120,max_timeout=120,
        timeouts={'copter':{'default_timeout_ns':30_000_000_000,'max_timeout_ns':30_000_000_000}},
        overrides={'plane':{'height_m':{'const':50.,'default':50.}},'copter':{'height_m':{'maximum':2.}}},
        success='Copter: measured climb +/-0.35 m, settled 2 s. Plane: 50 +/-5 m and 8..28 m/s, settled 2 s; flight remains reserved.')
    for name,p in [('Drive',DriveParameters),('Turn',TurnParameters)]:
        add(name,p,RoverStreamFactory(name),kind=ActionKind.CONTINUOUS,vehicles=frozenset({'rover'}),effects=(TwistTargetEffect,StopMotionEffect,ModeEffect),success='Continuous body setpoints until explicit cancel. Exit zeros the old stream, requests native HOLD and requires the existing observed stop barrier. New movement requires GUIDED again.')
    add('Goto',GotoParameters,GotoFactory(),kind=ActionKind.GOAL,vehicles=frozenset({'rover','copter'}),cap='goto',effects=MOTION+(ModeEffect,),timeout=45,max_timeout=45,
        overrides={'rover':{'z_m':{'const':0.,'default':0.}}},success='Existing spatial arrival, stability and stop barriers; ACK is not arrival. Rover zeroes its stream and requests native HOLD for exit braking; subsequent movement requires GUIDED.')
    add('Stop',Empty,RoverStopFactory(),kind=ActionKind.GOAL,vehicles=frozenset({'rover'}),effects=(ModeEffect,),success='Native HOLD confirmation plus fresh observed speed <=0.1 m/s settled 2 s; does not require entering GUIDED to stop.')
    for name,p,cap,kind in [('SetVelocity',VelocityParameters,'velocity',ActionKind.CONTINUOUS),('SetYaw',YawParameters,'yaw',ActionKind.GOAL),('Hold',Empty,'hold',ActionKind.CONTINUOUS)]:
        add(name,p,StreamFactory(name),kind=kind,vehicles=frozenset({'copter'}),cap=cap,effects=MOTION,
            success='SetYaw: observed yaw within 0.1 rad settled 1 s; continuous operations require explicit cancellation.')
    for name in ('ReturnHome',):
        add(name,Empty,ReturnFactory(),kind=ActionKind.GOAL,vehicles=frozenset({'rover','copter'}),cap='return_home',effects=(ModeEffect,),timeout=45,max_timeout=45,
            success='Rover: actual home <=0.75 m, <=0.1 m/s settled 2 s, native HOLD exit. Copter: observed touchdown and disarmed.')
    add('Land',Empty,BasicFactory('land'),kind=ActionKind.GOAL,vehicles=frozenset({'copter'}),effects=(LandEffect,),timeout=25,max_timeout=25,success='Observed ground, disarm and stability; native ACK is insufficient.')
    for name,p,effects,kind,timeout in [('SetGuidedTarget',GuidedTargetParameters,(FixedWingTargetEffect,),ActionKind.ONE_SHOT,20),
            ('Loiter',Empty,(ModeEffect,),ActionKind.ONE_SHOT,20),('AutoLand',Empty,(ModeEffect,DisarmEffect),ActionKind.GOAL,400)]:
        add(name,p,PlaneFactory(name),kind=kind,vehicles=frozenset({'plane'}),cap={'SetGuidedTarget':'guided_target','Loiter':'loiter','AutoLand':'autoland'}[name],effects=effects,timeout=timeout,max_timeout=timeout,
            success='AutoLand: actual ground <0.25 m, speed <1 m/s settled 3 s and authenticated disarm. Other operations confirm configuration only; flight remains reserved.')
    # RTL is shared by Rover/Copter and Plane, with an explicitly different
    # success predicate selected by the concrete factory, never by the engine.
    class RtlFactory(ReturnFactory):
        def validate_context(self,p,w,c):
            if c.target_kind=='plane':return PlaneFactory('RTL').validate_context(p,w,c)
            return super().validate_context(p,w,c)
        def start_with_context(self,p,w,c):
            return PlaneFactory('RTL').start_with_context(p,w,c) if c.target_kind=='plane' else super().start_with_context(p,w,c)
    add('RTL',Empty,RtlFactory(),kind=ActionKind.GOAL,cap='rtl',effects=(ModeEffect,),timeout=45,max_timeout=45,
        timeouts={'plane':{'default_timeout_ns':20_000_000_000,'max_timeout_ns':30_000_000_000}},
        success='Plane: native RTL mode adoption, not arrival or landing. Rover/Copter: physical ReturnHome goal.')
    from vehicle_autonomy.actions.composite.rescue import register_rescue
    register_rescue(registry)
