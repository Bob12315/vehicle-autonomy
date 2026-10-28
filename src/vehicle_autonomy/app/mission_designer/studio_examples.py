"""Definition templates; construction never runs Actions or sends commands."""
from copy import deepcopy
from vehicle_autonomy.actions.simulation.studio_demo import TARGET,TASK_RESULT


def node(identifier,kind,**kw):return dict(node_id=identifier,type=kind,**kw)
def edge(source,target,port='next'):return dict(edge_id='e_'+source+'_'+port.replace(':','_')+'_'+target,source=source,target=target,port=port)
def variable(schema,default=None,*,initialized=True):
    result=dict(schema=deepcopy(schema),max_age_s=120)
    if initialized:result['default']=default
    return result
def mission(identifier,name,target,kind,nodes,edges,**kw):
    return dict(schema_version=2,mission_id=identifier,revision=0,version='1.0.0',name=name,target=target,supported_vehicles=[kind],nodes=nodes,edges=edges,
        metadata=dict(tags=['simulation','standard-example'],description='Explicit simulation template; no automatic execution.'),**kw)


def cuadc(target,*,target_loss=False):
    text={'type':'string'};integer={'type':'integer'}
    inputs=dict(target=variable(TARGET,initialized=False),simulated_payload_slot=variable(integer,initialized=False),remaining_in=variable(integer,initialized=False))
    outputs=dict(operation_status=variable(text,initialized=False),task_result=variable(TASK_RESULT,initialized=False),
        current_target=variable(TARGET,initialized=False),remaining_out=variable(integer,initialized=False))
    parameters={k:dict(ref='submission.'+v) for k,v in [('target','target'),('simulated_payload_slot','simulated_payload_slot'),('remaining','remaining_in')]}
    bindings={k:dict(ref='submission.'+v) for k,v in [('operation_status','operation_status'),('task_result','task_result'),('current_target','current_target'),('remaining','remaining_out')]}
    child=mission('HandleTarget','HandleTarget · 软件仿真',target,'copter',[
        node('start','Start'),node('recover','Recovery'),
        node('confirm','Action',action_type='Sim.ConfirmTarget',input_bindings=deepcopy(parameters)),
        node('operate','Action',action_type='Sim.SimulatedTaskOperation',input_bindings=deepcopy(parameters),output_bindings=deepcopy(bindings)),
        node('lost','Action',action_type='Sim.RecoverLostTarget',input_bindings=deepcopy(parameters),output_bindings=deepcopy(bindings)),node('end','End')],
        [edge('start','recover'),edge('recover','confirm','try'),edge('confirm','operate'),edge('recover','lost','recover'),edge('recover','end')],
        blackboard={},interface=dict(inputs=inputs,outputs=outputs),execution_policy=dict(timeout_s=30))
    board=dict(detections=variable({'type':'array','items':TARGET},[]),selected_targets=variable({'type':'array','items':TARGET},[]),
        current_target=variable({'anyOf':[TARGET,{'type':'null'}]},None),simulated_payload_remaining=variable(integer,2),
        results=variable({'type':'array','items':TASK_RESULT},[]),mission_status=variable(text,'DRAFT'),selected_count=variable(integer,0))
    nodes=[node('start','Start'),node('preflight','Action',action_type='Sim.PreflightCheck',output_bindings={'mission_status':{'ref':'mission.mission_status'}}),
        node('observe','Action',action_type='Sim.ObserveArea'),node('detect','Action',action_type='Sim.DetectContainers',parameters=dict(simulate_target_loss=target_loss),output_bindings={'detections':{'ref':'mission.detections'}}),
        node('select','Action',action_type='Sim.SelectTargets',input_bindings={'detections':{'ref':'mission.detections'}},output_bindings={'selected_targets':{'ref':'mission.selected_targets'},'count':{'ref':'mission.selected_count'}}),
        node('condition','Condition',execution_policy=dict(expression=dict(op='eq',source='blackboard',path='mission.selected_count',value=2))),
        node('loop','ForEach',execution_policy=dict(collection={'ref':'mission.selected_targets'},max_iterations=2,on_item_failure='abort')),
        node('handle','SubMission',sub_mission=dict(mission_id='HandleTarget',version='1.0.0'),input_bindings=dict(target={'ref':'loop.current_item'},simulated_payload_slot={'ref':'loop.index'},remaining_in={'ref':'mission.simulated_payload_remaining'}),
            output_bindings=dict(task_result={'ref':'mission.results','mode':'append'},current_target={'ref':'mission.current_target'},remaining_out={'ref':'mission.simulated_payload_remaining'})),
        node('return_land','Action',action_type='Sim.ReturnAndLand',output_bindings={'mission_status':{'ref':'mission.mission_status'}}),
        node('missing','End',execution_policy={'outcome':'FAILED'}),node('unknown','End',execution_policy={'outcome':'UNKNOWN'}),node('end','End')]
    edges=[edge('start','preflight'),edge('preflight','observe'),edge('observe','detect'),edge('detect','select'),edge('select','condition'),
        edge('condition','loop','true'),edge('condition','missing','false'),edge('condition','unknown','unknown'),edge('condition','return_land'),edge('loop','handle','body'),edge('return_land','end')]
    parent=mission('CUADC_MultiTarget_Simulation','CUADC MultiTarget · 纯软件模拟',target,'copter',nodes,edges,blackboard=board,execution_policy=dict(timeout_s=120))
    parent['metadata'].update(observation_region_m=[30,35],geometry_source='declared_software_scene_geometry',
        warning='No real detection, autonomous aiming, release calculation, physical payload, takeoff, return or landing. Sim.* results are software records.')
    return child,parent


def rover_inspection(target):
    steps=[('state','GetVehicleState',{}),('guided','SetMode',{'mode':'GUIDED'}),('arm','Arm',{}),
        ('inspect','Goto',dict(x_m=1.,y_m=0.,z_m=0.)),('stop','Stop',{}),('guided_home','SetMode',{'mode':'GUIDED'}),
        ('home','Goto',dict(x_m=0.,y_m=0.,z_m=0.)),('stop_home','Stop',{}),('disarm','Disarm',{})]
    nodes=[node('start','Start'),*[node(i,'Action',action_type=name,parameters=p) for i,name,p in steps],node('end','End')]
    names=[n['node_id'] for n in nodes]
    return mission('Rover_Inspection','Rover 巡检 · 自有 SITL',target,'rover',nodes,[edge(a,b) for a,b in zip(names,names[1:])],blackboard={},execution_policy={'timeout_s':180})


def copter_inspection(target):
    steps=[('state','GetVehicleState',{}),('guided','SetMode',{'mode':'GUIDED'}),('arm','Arm',{}),('takeoff','Takeoff',{'height_m':1.5}),
        ('observe','Goto',dict(x_m=1.,y_m=0.,z_m=1.5)),('home_land','ReturnHome',{})]
    nodes=[node('start','Start'),*[node(i,'Action',action_type=name,parameters=p) for i,name,p in steps],node('end','End')]
    names=[n['node_id'] for n in nodes]
    return mission('Copter_Inspection','Copter 观测返航 · 自有 SITL',target,'copter',nodes,[edge(a,b) for a,b in zip(names,names[1:])],blackboard={},execution_policy={'timeout_s':180})


def plane_inspection(target):
    import math
    nodes=[node('start','Start'),node('state','Action',action_type='GetVehicleState'),node('manual','Action',action_type='SetMode',parameters={'mode':'MANUAL'}),
        node('arm','Action',action_type='Arm'),node('takeoff','Action',action_type='Takeoff',parameters={'height_m':50.}),
        node('navigate','Action',action_type='SetGuidedTarget',parameters={'altitude_amsl_m':634.},input_bindings=dict(
            latitude_deg=dict(source='world',path='vehicle.global_position.value.latitude_deg',frame='earth',max_age_s=3,offset=math.degrees(150/6378137.)),
            longitude_deg=dict(source='world',path='vehicle.global_position.value.longitude_deg',frame='earth',max_age_s=3))),
        node('observe','Wait',parameters={'duration_s':90.}),node('loiter','Action',action_type='Loiter'),node('loiter_wait','Wait',parameters={'duration_s':5.}),
        node('rtl','Action',action_type='RTL'),node('rtl_wait','Wait',parameters={'duration_s':5.}),node('land','Action',action_type='AutoLand'),node('end','End')]
    names=[n['node_id'] for n in nodes]
    d=mission('Plane_Inspection','Plane 导航与跑道降落 · 自有 SITL',target,'plane',nodes,[edge(a,b) for a,b in zip(names,names[1:])],blackboard={},execution_policy={'timeout_s':900})
    d['metadata']['warning']='Only the audited owned runway profile: 50 m takeoff / 634 m AMSL target. GUIDED/LOITER/RTL ACKs confirm configuration, not arrival.'
    return d
