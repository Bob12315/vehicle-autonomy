"""Read-only operator projection. Diagnostics never grant arming authority."""
import math
from vehicle_autonomy.contracts.core.serialization import to_json_value


def vehicle_display(info,world,profile,now):
    state=None if world is None else world.vehicle
    modes={} if profile is None else dict(profile.mode_ids)
    native=None if state is None else state.operation.native_mode
    names={f'ARDUPILOT_CUSTOM_{number}':name for name,number in modes.items()}
    names.setdefault('ARDUPILOT_CUSTOM_0','STABILIZE' if info['kind']=='copter' else 'MANUAL')
    pose=None if state is None else state.reported_pose
    twist=None if state is None else state.reported_twist
    fresh=False;age=None
    if pose is not None:
        try:age=now.elapsed_ns_since(pose.captured_at)/1e9
        except ValueError:pass
    if state is not None:
        try:fresh=bool(info.get('connected') and state.health.quality.value=='VALID' and 0<=now.elapsed_ns_since(state.published_at)<=3_000_000_000)
        except ValueError:pass
    armed=None if state is None else state.operation.armed
    height=None if pose is None else pose.value.position.z
    ground=bool(height is not None and abs(height)<=1.5)
    if info['kind']=='plane':
        choices=['MANUAL'] if fresh and ground and armed is False else ['GUIDED','LOITER','RTL'] if fresh and armed and height>=10 else []
        hint=('地面：MANUAL → 解锁 → 起飞。GUIDED / 盘旋 / RTL 仅供空中使用。' if ground else
              '空中：新动作须续接已确认的飞行控制；停止采用盘旋，RTL 不表示已着陆。')
    else:
        choices=['HOLD','GUIDED'] if info['kind']=='rover' else ['GUIDED','LOITER']
        hint=('先切换 GUIDED 并解锁，再授权按住操控；松开停车后需重新切换 GUIDED。' if info['kind']=='rover' else
              '先切换 GUIDED、解锁并起飞，再授权平移或转向；停止输入保持悬停，返航会降落。')
    telemetry=None if state is None else state.telemetry
    diagnostics={} if telemetry is None else {f.message_type:to_json_value(f) for f in telemetry.fields if f.message_type in ('GPS_RAW_INT','EKF_STATUS_REPORT','STATUSTEXT','SYS_STATUS')}
    if telemetry is not None:
        for field in telemetry.fields:
            if field.message_type not in diagnostics:continue
            try:recent=field.received_at is not None and 0<=now.elapsed_ns_since(field.received_at)<=3_000_000_000
            except ValueError:recent=False
            diagnostics[field.message_type]['receive_fresh']=recent
            if not recent:
                diagnostics[field.message_type]['receive_fresh']=False
                if field.value is not None:diagnostics[field.message_type]['availability']='STALE'
    heading=None
    if pose:
        q=pose.value.orientation
        heading=math.degrees(math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z)))
    return dict(mode_name=names.get(native,native or '未知'),mode_choices=choices if fresh else [],
        control_hint=hint if fresh else '等待新鲜、有效的车辆状态；连接成功不代表可以解锁。',
        source_system=None if telemetry is None else telemetry.source_system,
        pose_age_s=age,heading_enu_deg=heading,
        horizontal_speed_mps=None if twist is None else math.hypot(twist.value.linear.x,twist.value.linear.y),
        vertical_speed_mps=None if twist is None else twist.value.linear.z,
        battery=diagnostics.get('SYS_STATUS',{}).get('value') if diagnostics.get('SYS_STATUS',{}).get('receive_fresh') and diagnostics.get('SYS_STATUS',{}).get('availability')!='STALE' else None,diagnostics=diagnostics,
        airspeed_mps=None,arming_readiness='飞控检查结果以动作反馈及状态消息为准')
