"""Age-aware read-only projection. No stale normal values survive disconnects."""
from copy import deepcopy
import math


def dashboard(snapshot, now):
    def age(stamp):
        if not stamp or stamp.get('clock_domain_id') != str(now.clock_domain_id): return None
        delta=(now.monotonic_ns-stamp['monotonic_ns'])/1e9
        return delta if delta>=0 else None
    def recent(stamp):
        value=age(stamp)
        return value is not None and value<=3
    result=[]
    for info in snapshot['vehicles']:
        state=(info.get('world') or {}).get('vehicle') or {}
        fresh=bool(info.get('connected') and state.get('health',{}).get('quality')=='VALID' and recent(state.get('published_at')))
        pose=state.get('reported_pose');twist=state.get('reported_twist')
        pose=pose if fresh and pose and recent(pose.get('captured_at')) else None
        twist=twist if fresh and twist and recent(twist.get('captured_at')) else None
        fields={}
        for field in (state.get('telemetry') or {}).get('fields',[]):
            value=deepcopy(field)
            if not fresh or not recent(field.get('received_at')) or field.get('availability') in ('STALE','INVALID','MISSING'):
                value.update(value=None,receive_fresh=False)
            fields[field['message_type']]=value
        heading=None
        if pose:
            q=pose['value']['orientation']
            heading=math.degrees(math.atan2(2*(q['w']*q['z']+q['x']*q['y']),1-2*(q['y']**2+q['z']**2)))
        operation=state.get('operation',{}) if fresh else {}
        power=next((fields[k]['value'] for k in ('BATTERY_STATUS','SYS_STATUS') if fields.get(k,{}).get('value')),None)
        geo=state.get('global_position');geo=geo if fresh and geo and recent(geo.get('captured_at')) else None
        missions=[dict(id=m['id'],state=m['state'],release_safe=m.get('release_safe')) for m in snapshot.get('missions',[]) if m['target']==info['target']]
        actions=[dict(id=a['id'],name=a['name'],state=a['state'],safety=a.get('safety')) for a in snapshot.get('actions',[]) if a['target']==info['target']]
        result.append(dict(id=info['target'],type=info['kind'],connected=bool(info.get('connected')),fresh=fresh,
            environment='simulation' if info.get('owned_simulation') else 'unverified',
            telemetry_age_s=age(state.get('published_at')),pose_age_s=age((state.get('reported_pose') or {}).get('captured_at')),
            mode=info.get('display',{}).get('mode_name') if fresh else None,armed=operation.get('armed'),failsafe=operation.get('failsafe'),
            position=None if pose is None else pose['value']['position'],attitude=None if pose is None else pose['value']['orientation'],
            heading_deg=heading,altitude_m=None if pose is None else pose['value']['position']['z'],
            velocity=None if twist is None else twist['value']['linear'],global_position=None if geo is None else geo['value'],
            battery=power,gps=fields.get('GPS_RAW_INT',{}),ekf=fields.get('EKF_STATUS_REPORT',{}),
            status_text=fields.get('STATUSTEXT',{}),airspeed_mps=None,
            health=deepcopy(state.get('health')) if fresh else dict(quality='UNKNOWN',faults=['disconnected or stale telemetry']),
            authority={k:info.get(k) for k in ('system_send','action_send','deployment_send','lease_active','scope','session_id')},
            capabilities=info.get('capabilities',[]),missions=missions,actions=actions,
            control_hint=info.get('display',{}).get('control_hint'),fault=info.get('fault')))
    return dict(vehicles=result,fault=snapshot.get('fault'))
