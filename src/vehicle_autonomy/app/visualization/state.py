"""Project the existing VehicleState cut; never establish another vehicle feed."""
import math

from vehicle_autonomy.contracts.core.serialization import to_json_value

# Same conservative host-capture bound as the existing Vehicle Control view.
# This is a reported-pose visualization, never a navigation localization grant.
MAX_AGE_S=3.


def snapshot(service,target):
    driver=service.drivers[target]
    info,world=driver.read_view() if callable(getattr(driver,'read_view',None)) else (driver.info(),driver.snapshot())
    now=service.clock();vehicle=None if world is None else world.vehicle
    kind=info['kind'];reason=None;pose=None;twist=None;gps=None;diagnostics={}
    def age(stamp):
        if stamp is None:return None
        try:return now.elapsed_ns_since(stamp)/1e9
        except ValueError:return None
    def fresh(value):return value is not None and 0<=value<=MAX_AGE_S
    if vehicle and vehicle.telemetry:
        for field in vehicle.telemetry.fields:
            if field.message_type in ('GPS_RAW_INT','EKF_STATUS_REPORT'):
                diagnostics[field.message_type]=dict(value=to_json_value(field.value),age_s=age(field.received_at))
    if vehicle:
        if vehicle.global_position and fresh(age(vehicle.global_position.captured_at)):
            gps=to_json_value(vehicle.global_position.value)
        if vehicle.reported_pose and vehicle.reported_twist:
            pose=vehicle.reported_pose;twist=vehicle.reported_twist
    if not info.get('connected') or info.get('fault'):reason='vehicle disconnected or faulted'
    elif not vehicle or vehicle.health.quality.value!='VALID':reason='vehicle state invalid or unavailable'
    elif not pose or not twist or pose.frame_id!='odom' or twist.frame_id not in ('odom','base_link'):reason='qualified ENU odom pose/twist unavailable'
    elif not all(fresh(age(x)) for x in (vehicle.published_at,pose.captured_at,twist.captured_at)):reason='vehicle telemetry stale or clock domain invalid'
    elif kind in ('rover','plane') and gps is None:reason='GPS-derived local projection lacks a fresh valid GPS fix'
    ekf=diagnostics.get('EKF_STATUS_REPORT',{});ekf_health='UNKNOWN'
    if ekf.get('value'):
        flags=ekf['value']['flags']
        if not flags&1 or not flags&2 or not flags&(8|16):reason='EKF attitude/velocity/local position unhealthy';ekf_health='UNHEALTHY'
        elif ekf.get('age_s') is not None and 0<=ekf['age_s']<=3:ekf_health='REPORTED_HEALTHY'
    epoch=None if world is None else str(world.version.generation_id)+':'+str(info.get('session_id'))
    manifest=getattr(getattr(driver,'ownership',None),'manifest',None)
    from .simulation import identity
    return dict(schema=1,target=target,kind=kind,environment='simulation' if info.get('owned_simulation') else 'hardware_readonly',
        epoch=epoch,simulation_id=identity(manifest) if manifest and info.get('owned_simulation') else None,origin=dict(id=epoch,frame='odom',axes='ENU',body='FLU',
            basis='AP GPS_GLOBAL_ORIGIN projection' if kind in ('rover','plane') else 'AP local EKF origin',
            altitude_reference='native local-origin relative; global GPS altitude is AMSL',
            geodetic_origin=None if info.get('local_reference') is None else dict(latitude_deg=info['local_reference'][0],longitude_deg=info['local_reference'][1],altitude_amsl_m=info['local_reference'][2])),
        valid=reason is None,reason=reason,source_now_ns=str(now.monotonic_ns),
        sample_ns=None if pose is None else str(pose.captured_at.monotonic_ns),age_s=None if pose is None else age(pose.captured_at),
        pose=to_json_value(pose.value) if reason is None else None,
        twist=to_json_value(twist.value) if reason is None else None,twist_frame=None if twist is None else twist.frame_id,
        gps=gps,gps_age_s=None if vehicle is None or vehicle.global_position is None else age(vehicle.global_position.captured_at),
        gps_sample_ns=None if gps is None else str(vehicle.global_position.captured_at.monotonic_ns),max_age_s=MAX_AGE_S,
        diagnostics=diagnostics,ekf_health=ekf_health,armed=None if vehicle is None else vehicle.operation.armed)


def finite_vector(value,size):
    if type(value) is not list or len(value)!=size or any(type(v) not in (int,float) or not math.isfinite(v) for v in value):raise ValueError('finite coordinate vector required')
    return [float(v) for v in value]
