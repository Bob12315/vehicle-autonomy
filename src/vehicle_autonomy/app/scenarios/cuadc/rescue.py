"""Rescue-2026 Studio template, using the existing graph/blackboard engine."""
from vehicle_autonomy.actions.composite.rescue import DROP, TARGET
from vehicle_autonomy.app.mission_designer.studio_examples import node, edge, mission, variable


def template(target=''):
    nodes=[node('start','Start')];edges=[];last='start'
    def action(identifier,name,parameters=None,bindings=None,**extra):
        nonlocal last
        nodes.append(node(identifier,'Action',action_type=name,action_contract_version='1.0.0',
            parameters=parameters or {},input_bindings=bindings or {},**extra))
        edges.append(edge(last,identifier));last=identifier
    def go(identifier,x,y,z,speed=10.,**extra):
        action(identifier,'Rescue.Goto',dict(x_m=x,y_m=y,z_m=z,speed_mps=speed,**extra))
    nodes.append(node('settle_estimator','Wait',parameters={'duration_s':45.}))
    edges.append(edge(last,'settle_estimator'));last='settle_estimator'
    action('guided','SetMode',{'mode':'GUIDED'})
    action('arm','Arm')
    action('takeoff_4_5m','Rescue.Takeoff',{'height_m':4.5})
    go('goto_drop_center_5m',0.,32.5,5.)
    action('drop_scan_capture','Rescue.CaptureView')
    action('drop_scan_fuse','Rescue.FuseViews',bindings={'objects':{'ref':'node.drop_scan_capture.output.objects'}})
    action('select_gps_drop_targets','Rescue.SelectDropTargets',{'first_release_target_ey':1.,'second_release_target_ey':-.5},bindings={'objects':{'ref':'node.drop_scan_fuse.output.objects'}},
        output_bindings={'targets':{'ref':'mission.drop_targets'}})
    nodes.append(node('drop_loop','ForEach',execution_policy={'collection':{'ref':'mission.drop_targets'},'max_iterations':2,'on_item_failure':'abort'}))
    edges.append(edge(last,'drop_loop'));last='drop_loop'
    bindings={name:{'ref':'loop.current_item.target.'+value} for name,value in [('x_m','x_m'),('y_m','y_m')]}
    nodes.append(node('drop_approach','Action',action_type='Rescue.Goto',action_contract_version='1.0.0',
        parameters={'z_m':3.,'speed_mps':5.,'tolerance_xy_m':.25},input_bindings=bindings))
    edges.append(edge('drop_loop','drop_approach','body'));last='drop_approach'
    action('drop_confirm','Rescue.ConfirmTarget',bindings={'target':{'ref':'loop.current_item.target'}})
    action('drop_align','Rescue.AlignDescend',bindings={'target':{'ref':'node.drop_confirm.output.target'},'release_target_ey':{'ref':'loop.current_item.release_target_ey'}})
    action('drop_release','Rescue.ReleasePayload',bindings={'target':{'ref':'node.drop_confirm.output.target'},
        'servo_outputs':{'ref':'loop.current_item.servo_outputs'},'alignment_confirmed':{'ref':'node.drop_align.output.alignment_confirmed'},
        'release_target_ey':{'ref':'loop.current_item.release_target_ey'}})
    action('drop_climb','Rescue.Goto',{'z_m':2.5,'speed_mps':5.,'tolerance_z_m':.1},bindings=bindings)
    last='drop_loop'
    go('goto_recon_entry_4m',-3.,56.,4.)
    for i,(x,y) in enumerate(((-3.,56.),(3.,56.),(3.,59.),(-3.,59.)),1):
        go('recon_scan_goto_'+str(i),x,y,3.,5.,tolerance_xy_m=.4)
        action('recon_capture_'+str(i),'Rescue.CaptureReconView',output_bindings={'objects':{'ref':'mission.recon_views','mode':'append'}})
    go('return_home_gps',0.,0.,4.)
    go('descend_home_2_5m',0.,0.,2.5,tolerance_z_m=.25)
    action('landing_marker','Rescue.LandingTarget')
    action('final_land_align','Rescue.AlignDescend',{'target_altitude_m':.3,'final_settle_time_s':.5},
        bindings={'target':{'ref':'node.landing_marker.output.target'}})
    action('land_home','Land')
    nodes.append(node('end','End'));edges.append(edge(last,'end'))
    definition=mission('Rescue_2026_FullAuto','CUADC 2026 全自主救援 · 本机 PT',target,'copter',nodes,edges,
        blackboard={'drop_targets':variable({'type':'array','items':DROP},[]),
            'recon_views':variable({'type':'array','items':{'type':'array','items':TARGET}},[])},execution_policy={'timeout_s':1800})
    definition['version']='1.1.1'
    definition['metadata'].update(description='4.5 米起飞、5 米投放区采样、投放画面偏移 +1/-0.5、四角侦察航点 5 m/s、返航 H 标记对准降落。',
        source_recipe='simulation/missions/cuadc2026/rescue_2026_source.json',scene_id='CUADC2026',
        simulation_only=True,requires_send=True,required_capabilities=['rescue_flight','rescue_vision','rescue_payload'],
        detector_classes=['bucket','H'],detector_backend='ultralytics_pt',
        coordinate_convention='Explicit odom ENU, field +Y; heading ENU pi/2. No implicit GPS/map transform.',
        servo_mapping={'8':{'payload':'payload_1','release_pwm':1800,'hold_pwm':1370},'9':{'payload':'payload_2','release_pwm':1835,'hold_pwm':1335}},
        migration_changes=['User revision: transit horizontal velocity limit 10 m/s; drop approach/climb and all four reconnaissance waypoints 5 m/s; vertical and alignment descent limits retained.',
            'A single observed bucket receives both payloads; two buckets receive one each.',
            'No unobserved fallback-center release. No continue-on-failure or success-on-alignment-timeout.',
            'FuseViews deduplicates fresh already-localized observations; it does not claim GPS triangulation.',
            'User revision: virtual-camera ey offsets +1/-0.5 are explicit selection and release parameters, not metres; physical calibration requires separate validation.',
            'User revision: reconnaissance retains the four original corners and removes the two midpoint stops.'])
    definition['blackboard']['drop_targets']['max_age_s']=180
    return definition
