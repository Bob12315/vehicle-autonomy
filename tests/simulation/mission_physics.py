"""Independent Gazebo checks using the original Phase 1/2/3 physical limits."""
import math


def target_reference(f,action):
    from pymavlink.dialects.v20 import ardupilotmega as mav
    start=action['history'][0]['at_ns'];end=action['history'][-1]['at_ns'];matches=[]
    for w in f.writer:
        if not start<=w['host_ns']<=end:continue
        messages=mav.MAVLink(None).parse_buffer(bytes.fromhex(w['raw_hex'])) or []
        for m in messages:
            if m.get_type()=='COMMAND_INT' and m.command==mav.MAV_CMD_DO_REPOSITION:matches.append((w,m))
    if len(matches)!=1:raise AssertionError('native map target must have exactly one actual COMMAND_INT Writer frame')
    w,m=matches[0];p=action['parameters']
    if abs(m.x/1e7-p['latitude_deg'])>1e-7 or abs(m.y/1e7-p['longitude_deg'])>1e-7 or abs(m.z-p['altitude_amsl_m'])>.001:
        raise AssertionError('actual native Writer target differs from UI/Mission parameters')
    gps=[r for r in f.received if r['type']=='GLOBAL_POSITION_INT' and r['host_ns']<=w['host_ns']]
    if not gps or w['host_ns']-gps[-1]['host_ns']>500_000_000:raise AssertionError('target reference lacks fresh AP geodetic sample')
    geo=gps[-1]['payload'];truth=min(f.trajectory,key=lambda t:abs(t['host_ns']-w['host_ns']))
    if abs(truth['host_ns']-w['host_ns'])>500_000_000:raise AssertionError('target reference lacks contemporaneous Gazebo truth')
    latitude,longitude=geo['lat']/1e7,geo['lon']/1e7
    center=[truth['position'][0]+6378137*math.cos(math.radians(latitude))*math.radians(m.y/1e7-longitude),
            truth['position'][1]+6378137*math.radians(m.x/1e7-latitude)]
    return dict(center=center,sent_ns=w['host_ns'],writer_index=f.writer.index(w),
        source='owned speed-one AP geodetic offset + independent Gazebo ENU; observation only',
        target=dict(latitude_deg=m.x/1e7,longitude_deg=m.y/1e7,altitude_amsl_m=m.z))


def target_motion(f,reference,*,end_ns=None):
    points=[t for t in f.trajectory if reference['sent_ns']<=t['host_ns']<=min(end_ns or 2**63,reference['sent_ns']+90_000_000_000)]
    stable=None;rotation=0;last=None
    for t in points:
        if last is not None:rotation+=abs(math.atan2(math.sin(t['yaw']-last),math.cos(t['yaw']-last)))
        last=t['yaw'];p=t['position'];error=math.hypot(p[0]-reference['center'][0],p[1]-reference['center'][1])
        good=error<=120 and abs(p[2]-f.initial.z_m-50)<=7 and t['speed'] is not None and 8<=t['speed']<=28
        stable=(stable if stable is not None else t['host_ns']) if good else None
        if stable is not None and t['host_ns']-stable>=3_000_000_000 and rotation>=math.pi/2:
            return dict(passed=True,center_error_m=error,rotation_rad=rotation,speed_mps=t['speed'],reference=reference)
    return None


def mission_result(f,result):
    c=result['mission_checkpoints'];kind=f.kind
    if kind in ('rover','copter'):
        reached=c['Goto']['truth'];home=c['ReturnHome']['truth']
        goto_error=math.hypot(reached[0]-f.initial.x_m-2,reached[1]-f.initial.y_m-1)
        home_error=math.hypot(home[0]-f.initial.x_m,home[1]-f.initial.y_m)
        if goto_error>.75 or home_error>.75:raise AssertionError('browser Mission physical Goto/ReturnHome error')
        if c['ReturnHome']['speed_mps']>(.1 if kind=='rover' else .15):raise AssertionError('Mission physical stop not confirmed')
        if kind=='copter' and (abs(c['Takeoff']['truth'][2]-f.initial.z_m-1.5)>.35 or home[2]-f.initial.z_m>.2):
            raise AssertionError('Copter Mission physical climb/landing error')
        return dict(goto_error_m=goto_error,home_error_m=home_error,home_speed_mps=c['ReturnHome']['speed_mps'])
    land=c['AutoLand'];p=land['truth'];distance=math.hypot(p[0]-f.initial.x_m,p[1]-f.initial.y_m)
    takeoff=c['Takeoff']['truth'][2]-f.initial.z_m
    end=land['action']['history'][-1]['at_ns']
    rollout=[t for t in f.trajectory if t['host_ns']<=end and t['position'][2]-f.initial.z_m<1 and (t['speed'] or 0)>8]
    if takeoff<45 or not rollout or max(math.hypot(t['position'][0]-f.initial.x_m,t['position'][1]-f.initial.y_m) for t in rollout)<10:
        raise AssertionError('Mission Plane physical ground rollout/climb missing')
    if p[2]-f.initial.z_m>.25 or land['speed_mps']>=1 or distance>80 or abs(p[1]-f.initial.y_m)>15:
        raise AssertionError('Mission Plane physical landing outside original runway limits')
    reference=c['SetGuidedTarget'].get('native_reference') or target_reference(f,c['SetGuidedTarget']['action'])
    motion=target_motion(f,reference,end_ns=c['Loiter']['action']['history'][0]['at_ns'])
    if motion is None:raise AssertionError('Mission native target lacked actual flight within original 90s / 120m / 3s limits')
    return dict(takeoff_height_m=takeoff,rollout_samples=len(rollout),target=motion,landing_error_m=distance,
        landing_height_m=p[2]-f.initial.z_m,landing_speed_mps=land['speed_mps'])


def no_expired_motion(f,action):
    from pymavlink.dialects.v20 import ardupilotmega as mav
    deadline=action['input_deadline_ns'];bad=[];checked=0
    for w in f.writer:
        if w['host_ns']<deadline:continue
        # Restrict to this Action's cleanup window, before another authorization.
        end=action['history'][-1]['at_ns']
        if w['host_ns']>end:continue
        for m in mav.MAVLink(None).parse_buffer(bytes.fromhex(w['raw_hex'])) or []:
            if m.get_type()=='SET_POSITION_TARGET_LOCAL_NED':
                checked+=1
                if any(abs(v)>1e-9 for v in (m.vx,m.vy,m.vz,m.yaw_rate)):bad.append(w['host_ns'])
    if bad:raise AssertionError('expired manual nonzero motion reached actual Writer')
    return dict(expired_motion_writer_calls=0,cleanup_velocity_frames_checked=checked)
