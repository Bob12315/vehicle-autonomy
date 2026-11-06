"""Presentation-only Action catalog. No registration, schema or execution changes.

The keys below are exact registered identities, never aliases for execution.
Unknown registrations remain visible in Uncategorized with their original ID.
"""
from copy import deepcopy


def bilingual(zh, en):
    return {'zh-CN': zh, 'en-US': en}


CATEGORIES = {
    key: dict(label=bilingual(zh, en), icon=icon)
    for key, zh, en, icon in [
        ('vehicle', '车辆基础控制', 'Vehicle control', '◇'),
        ('navigation', '运动与导航', 'Motion and navigation', '➜'),
        ('safety', '安全与状态', 'Safety and state', '⊙'),
        ('perception', '感知与识别', 'Perception', '◎'),
        ('actuation', '设备与执行器', 'Devices and actuators', '⚙'),
        ('data', '数据与计算', 'Data and computation', '∑'),
        ('integration', '外部能力', 'External capabilities', '⇄'),
        ('composite', '复合任务能力', 'Composite capabilities', '▦'),
        ('uncategorized', '未分类', 'Uncategorized', '?'),
        ('logic', '逻辑编排', 'Logic', '⑂'),
        ('submission', '子任务', 'Sub-missions', '▣'),
    ]
}

# Audited against each actual factory and its parameter validation, not its filename.
ACTION_TEXT = {
    'Arm': ('vehicle', '解锁车辆', 'Arm vehicle', '请求解锁，并等待命令和请求之后的真实解锁状态确认。'),
    'Disarm': ('vehicle', '锁定车辆', 'Disarm vehicle', '请求上锁；飞行器必须符合实测静止地面条件，禁止空中上锁。'),
    'SetMode': ('vehicle', '切换模式', 'Switch mode', '切换当前车辆已审计模式；模式生效不代表已抵达目标。'),
    'Takeoff': ('vehicle', '起飞', 'Take off', '多旋翼按目标高度起飞；固定翼只支持已审计的 50 米跑道起飞配置。'),
    'Land': ('vehicle', '降落', 'Land', '多旋翼降落，并等待落地、上锁和稳定状态确认。'),
    'AutoLand': ('vehicle', '固定翼自动着陆', 'Fixed-wing autoland', '执行已审计的固定翼跑道着陆，观察近地高度、低速稳定和上锁。'),
    'Drive': ('navigation', '受控行驶', 'Drive', '持续发送地面车车体前向速度和转向角速度；取消后等待保持模式与停车确认。'),
    'Turn': ('navigation', '停车转向', 'Turn', '地面车以零线速度和有界偏航角速度转向；实际适用性由已审计驱动配置决定。'),
    'Goto': ('navigation', '前往目标位置', 'Go to position', '前往里程计东北天坐标位置，等待空间到达、稳定和停止确认；地面车高度固定为零，退出后保持 HOLD，后续运动前需切换 GUIDED。'),
    'ReturnHome': ('navigation', '返回起点', 'Return home', '地面车观察回到起点并停车；多旋翼观察返航落地并上锁。'),
    'RTL': ('navigation', '原生返航', 'Native return to launch', '地面车和多旋翼按物理返航条件完成；固定翼只确认原生返航模式，不能声称抵达或着陆。'),
    'SetGuidedTarget': ('navigation', '设置固定翼导航目标', 'Set fixed-wing guided target', '配置固定翼经纬度及海拔目标；仅确认配置，不确认到达。飞行状态需满足准入条件。'),
    'SetVelocity': ('navigation', '持续速度控制', 'Set velocity', '在里程计东北天或车体前左上坐标系持续给定多旋翼速度；必须显式取消并确认退出。'),
    'SetYaw': ('navigation', '设置航向', 'Set yaw', '将多旋翼里程计航向调整到指定弧度角，并确认角度稳定。'),
    'Stop': ('safety', '停止运动', 'Stop motion', '地面车进入保持模式，并以新鲜遥测确认速度不超过 0.1 米/秒、稳定 2 秒。'),
    'Hold': ('safety', '保持当前位置', 'Hold position', '在引导模式持续保持多旋翼当前位置；取消时遵守原有停止屏障。'),
    'Loiter': ('safety', '固定翼盘旋保持', 'Fixed-wing loiter', '请求固定翼盘旋模式；固定翼保持飞行速度，此操作不是悬停。'),
    'GetVehicleState': ('safety', '状态查询', 'Read vehicle state', '读取不可变世界状态、采样时间和新鲜度；不授予车辆控制权。'),
    'NavigateToPose': ('integration', '原生导航到位姿', 'Navigate to pose with Nav2', '调用原生 Nav2，结合独立新鲜地图位姿、导航生产者退出和车辆停车验证完成。'),
    'navigation.follow_path': ('navigation', '路径跟踪', 'Follow path', '跟踪经过校验并绑定坐标系、地图代际和车辆几何模型的地面车路径。'),
    'scenario.maneuver': ('navigation', '车辆机动', 'Vehicle maneuver', '在合格地面车场景中执行有限行驶、到访、转向、绕圈或等待；不是实时避障。'),
    'cuadc.inspect': ('composite', '目标巡检', 'Inspect target', '读取来源白名单中的新鲜目标，按评分选择并接近；不是一个真实视觉检测器。'),
    'cuadc.approach_release': ('composite', '接近目标并请求仿真载荷执行', 'Approach and request simulated release', '接近目标并等待停止，再发出受控载荷效果请求；当前使用仿真载荷确认，不能作为实机执行能力。'),
    'sitl.unarmed_mode': ('vehicle', '未解锁模式验证', 'Disarmed SITL mode check', '仅在未解锁飞控软件仿真中验证模式命令和随后状态。'),
    'sitl.arm': ('vehicle', '仿真解锁验证', 'SITL arm check', '显式授权的飞控软件仿真解锁步骤，受现有发送门和安全策略限制。'),
    'sitl.disarm': ('vehicle', '仿真上锁验证', 'SITL disarm check', '显式飞控软件仿真上锁步骤，等待原有命令确认。'),
    'Sim.PreflightCheck': ('safety', '仿真任务预检', 'Simulated preflight check', '检查软件演示的任务上下文并生成软件记录；不验证实机适航状态。'),
    'Sim.ObserveArea': ('perception', '仿真区域观测记录', 'Simulated area observation', '返回声明的软件场景区域，不读取相机，也不进行真实观测。'),
    'Sim.DetectContainers': ('perception', '仿真容器检测记录', 'Simulated container detections', '返回确定性场景目标记录，可模拟丢失；不运行图像检测。'),
    'Sim.SelectTargets': ('data', '仿真目标筛选', 'Select simulated targets', '按可信物理尺寸选择两个目标，不以像素框面积代替真实物理大小。'),
    'Sim.ConfirmTarget': ('perception', '仿真目标确认', 'Confirm simulated target', '验证当前软件目标是否有效；可触发软件目标丢失恢复。'),
    'Sim.SimulatedTaskOperation': ('actuation', '记录模拟任务操作', 'Record simulated task operation', '只更新软件槽位、数量和结果，不操作舵机、相机或物理载荷。'),
    'Sim.RecoverLostTarget': ('composite', '仿真目标丢失恢复', 'Recover simulated lost target', '记录目标丢失恢复结果，不消耗软件任务槽位；不控制车辆。'),
    'Sim.ReturnAndLand': ('composite', '仿真返航降落记录', 'Record simulated return and landing', '仅记录软件任务结束；不会发出返航、起飞或降落命令。'),
}
for _name, _category, _zh in [
    ('arm','vehicle','解锁车辆'), ('disarm','vehicle','锁定车辆'),
    ('takeoff','vehicle','起飞'), ('land','vehicle','降落'),
    ('goto','navigation','前往已解析目标'), ('return_home','navigation','返回已解析起点'),
    ('hold','safety','有限保持当前位置'), ('stop','safety','停止运动'),
]:
    ACTION_TEXT['basic.'+_name] = (_category, _zh+'（基础契约）', 'Basic '+_name.replace('_',' '),
        '早期有限仿真动作契约。需要显式环境版本、车型和合格定位；目标须预先解析，不能与同名独立动作互换。')

for _name, _category, _zh, _en, _description in [
    ('Takeoff','vehicle','救援起飞','Rescue takeoff','独立救援仿真配置内起飞至 4.5 米；仍须经过原有发送门和物理高度确认。'),
    ('Goto','navigation','救援航点飞行','Rescue waypoint','在明确绑定的救援 ENU 场地内限速飞行，等待到达、低速稳定和退出停止确认。'),
    ('CaptureView','perception','采集投放区目标','Capture drop view','读取本机 PT 识别器发布的新鲜已定位桶观测；不使用地图真值标签。'),
    ('CaptureReconView','perception','采集侦察区目标','Capture recon view','读取 56/59 米区域的新鲜 PT 目标观测，用于任务结果记录。'),
    ('LandingTarget','perception','获取降落 H 标记','Acquire landing marker','要求起降区内存在新鲜已定位 H 观测；缺失时失败。'),
    ('FuseViews','data','整理观测目标','Deduplicate observed targets','去重已经定位的新鲜目标；不声称完成 GPS 三角定位。'),
    ('SelectDropTargets','data','选择救援投放目标','Select rescue targets','最多选择两个已观测目标；一个桶接收双载荷，两个桶各接收一个。'),
    ('ConfirmTarget','perception','重新确认锁定目标','Reconfirm selected target','接近后仅在同一来源、同一类别、原位置附近唯一新鲜观测匹配时重新确认；缺失或歧义时失败。'),
    ('AlignDescend','navigation','对准并下降','Align and descend','读取锁定视觉目标，在对准窗口内下降；丢失时立即请求零速度并限时重获，超时失败，退出经过原有停止屏障。'),
    ('ReleasePayload','actuation','请求双通道仿真投放','Request simulated payload release','仅将明确的 8/9 通道配置映射至 Gazebo 双瓶脱离；不发送实机 PWM 或新增 MAVLink 写入通路。'),
]:
    ACTION_TEXT['Rescue.'+_name]=(_category,_zh,_en,_description)

# Label, explanation, physical unit. Unknown fields keep their schema text/key.
PARAMETERS = {}
def parameter(key, label, help, unit=''):
    PARAMETERS[key] = dict(label=bilingual(label,key.replace('_',' ')),
                          description=bilingual(help, 'Original parameter: '+key), unit=unit)

for key, label, help, unit in [
    ('mode','飞控模式','只能选择当前车辆配置已审计的模式；模式生效不代表物理到达。',''),
    ('height_m','目标高度','多旋翼为当前起飞参考的相对爬升高度；固定翼使用独立已审计跑道高度。','m'),
    ('x_m','X 方向目标位置','普通前往目标使用里程计东向坐标；原生导航使用已绑定地图的 X 坐标。','m'),
    ('y_m','Y 方向目标位置','普通前往目标使用里程计北向坐标；原生导航使用已绑定地图的 Y 坐标。','m'),
    ('z_m','向上目标高度','里程计东北天坐标的向上分量；地面车只允许零高度。','m'),
    ('vx_mps','X 方向速度','里程计坐标为向东；车体坐标为向前，由坐标系参数决定。','m/s'),
    ('vy_mps','Y 方向速度','里程计坐标为向北；车体坐标为向左，由坐标系参数决定。','m/s'),
    ('vz_mps','Z 方向速度','里程计及车体约定均为向上。','m/s'),
    ('yaw_rad','目标航向角','里程计约定东向为零、逆时针为正；原生导航使用绑定地图的偏航角。','rad'),
    ('yaw_rate_rad_s','转向角速度','偏航角速度，采用所选坐标系的右手约定。','rad/s'),
    ('speed_mps','行驶速度','地面车沿车体前向的线速度；是否允许倒车由动作及车型约束决定。','m/s'),
    ('frame','控制坐标系','odom 表示里程计东北天；base_link 表示车体前左上；其他坐标需显式绑定。',''),
    ('latitude_deg','目标纬度','WGS84 纬度，不是局部位置坐标。','°'),
    ('longitude_deg','目标经度','WGS84 经度，不是局部位置坐标。','°'),
    ('altitude_amsl_m','目标海拔高度','相对平均海平面的绝对海拔；固定翼准入还检查相对起点的 20～140 米范围。','m AMSL'),
    ('altitude_m','观测目标高度','仿真目标动作使用的里程计高度，允许 0～2 米。','m'),
    ('timeout_ns','执行超时时间','编辑器显示秒，保存为整数纳秒；必须满足动作自身期限约束。','ns'),
    ('duration_ns','持续时间','编辑器显示秒，保存为整数纳秒；不得超过执行超时。','ns'),
    ('duration_s','持续时间','有限等待或机动时长；不表示无限期执行。','s'),
    ('arrival_margin_m','到达位置容差','基础动作要求 0.1～0.75 米；容差不替代稳定和停止确认。','m'),
    ('vehicle_kind','车辆类型','基础目标契约支持地面车和多旋翼；起飞和降落仅多旋翼。',''),
    ('environment','环境版本引用','必须引用当前已绑定的环境及其代际；不能自行拼接为有效授权。',''),
    ('target','目标','按动作契约输入已解析位置或带来源的软件目标对象，不能仅凭名称执行。',''),
    ('native_mode','原生模式名称','诊断契约中请求的飞控原生模式名称。',''),
    ('custom_mode_id','原生模式编号','必须与已审计飞控模式名称一致的数字编号。',''),
    ('map_epoch','地图代际','必须匹配当前经过校验的地图代际；过期地图不可执行导航。',''),
    ('request_id','路径请求标识','路径规划请求的原始标识，用于校验来源。',''),
    ('frame_epoch','坐标系代际','路径使用的明确坐标系代际，必须与运行时一致。',''),
    ('source_generation','数据源代际','保留路径来源代际，防止复用失效数据。',''),
    ('file_sha256','路径文件摘要','已校验路径文件的 SHA-256 摘要，不是任意文件路径。',''),
    ('binding','坐标变换绑定','显式平面变换、误差界限和原点；不自动推断地图变换。',''),
    ('poses','路径位姿序列','经过资格检查并绑定到里程计坐标的路径位姿。',''),
    ('stop_turn','停车转向','在原动作支持的条件下使用停车转向策略，不绕过车辆几何约束。',''),
    ('allow_reverse','允许倒车','必须明确允许且受车辆运动学模型限制，不会自动启用倒车。',''),
    ('model','车辆几何模型','车辆参考点、足迹和能力参数，必须来自合格场景配置。',''),
    ('kind','机动类型','有限行驶、到访、转向、绕圈或等待；不是车辆类型。',''),
    ('start','起始位姿','已批准机动的起始位置与航向。',''),
    ('end','结束位姿','已批准机动的终止位置与航向。',''),
    ('path','机动路径','已批准的有限路径，场景机动要求 2～4096 个位姿。',''),
    ('turn_rad','机动转角','有限转角；场景机动不超过正负三圈。','rad'),
    ('radius_m','绕圈半径','合格绕圈动作使用 1.5～3 米半径。','m'),
    ('region','目标搜索区域','明确的里程计矩形区域，包含边界及坐标系。',''),
    ('payload_id','仿真载荷标识','仅在有对应能力的多旋翼仿真中使用；不是实机执行器凭据。',''),
    ('scores','目标评分表','目标类别和正整数评分，不使用像素面积代替物理尺寸。',''),
    ('allowed_sources','允许的目标来源','只接受这些来源前缀产生的新鲜目标；保留原始字符串。',''),
    ('detections','检测记录列表','由声明的软件场景产生的目标记录，不是实时视觉检测结果。',''),
    ('simulate_target_loss','模拟目标丢失','仅影响软件演示中目标确认的结果。',''),
    ('simulated_payload_slot','模拟任务槽位','软件计数槽位，不对应真实物理通道。',''),
    ('remaining','剩余任务数量','软件库存剩余数量；模拟操作完成才递减。',''),
    ('physical_diameter_m','物理直径','显式声明的物理尺寸，不从像素框直接推断。','m'),
    ('physical_size_source','物理尺寸来源','物理尺寸的原始来源说明，用于可信筛选。',''),
    ('bbox_area_px','像素框面积','像素面积，仅作诊断，不能替代物理尺寸排序。','px²'),
    ('lose_on_confirmation','确认时模拟丢失','软件演示分支；不修改真实传感器。',''),
    ('valid','记录有效','表示当前输入记录是否满足其生产者声明，不授予车辆控制权。',''),
    ('position','目标位置','保留父对象声明的坐标系、单位和参考原点。',''),
    ('x','X 分量','采用父对象定义的单位与坐标系，不隐式进行坐标变换。',''),
    ('y','Y 分量','采用父对象定义的单位与坐标系，不隐式进行坐标变换。',''),
    ('z','Z 分量','采用父对象定义的单位与坐标系，不隐式进行坐标变换。',''),
    ('yaw','平面航向','父位姿坐标系内的平面航向角。','rad'),
    ('base_to_reference_x_m','车体到参考点偏移','车体原点到运动学参考点的 X 方向偏移。','m'),
    ('cross_track_m','横向误差界限','规划绑定允许的横向误差界限。','m'),
    ('footprint_radius_m','足迹半径','合格车辆模型的平面足迹半径。','m'),
    ('max_speed_mps','最大速度','车辆模型声明的最大速度。','m/s'),
    ('max_yaw_rate_rps','最大偏航角速度','车辆模型声明的最大偏航角速度。','rad/s'),
    ('path_clearance_m','路径净空','经过验证的路径与障碍之间的净空。','m'),
    ('min_x','区域最小 X','父区域坐标系内的最小 X 边界。','m'),
    ('max_x','区域最大 X','父区域坐标系内的最大 X 边界。','m'),
    ('min_y','区域最小 Y','父区域坐标系内的最小 Y 边界。','m'),
    ('max_y','区域最大 Y','父区域坐标系内的最大 Y 边界。','m'),
    ('id','标识','原始对象标识，不做翻译或重命名。',''),
    ('name','名称','程序或资源的原始名称，输入值保持不变。',''),
    ('version','版本','明确的原始版本号。',''),
    ('revision','修订号','资源修订号，不能替代代际。',''),
    ('generation_id','代际标识','防止跨会话复用资源的原始代际标识。',''),
    ('resource_id','资源标识','当前注册资源的原始标识。',''),
    ('model_id','模型标识','合格车辆运动学模型的原始标识。',''),
    ('reference_point','车辆参考点','车辆几何与规划共同采用的参考点。',''),
    ('capabilities','模型能力','模型声明的能力列表，不授予新的控制权限。',''),
    ('motion_effects','运动效果集合','模型允许的原始效果类型。',''),
]: parameter(key,label,help,unit)

for key,label in {
    'result':'动作结果','world':'世界状态快照','home':'起点参考','context':'执行上下文','read_only':'只读结果',
    'confirmed':'确认结果','physical_arrival_claim':'物理到达声明','physical_goal_observed':'已观测物理目标',
    'armed':'是否已解锁','kind':'类型','mission_status':'任务状态','simulation':'软件仿真标记',
    'near_m':'区域近端距离','far_m':'区域远端距离','source':'数据来源','physical_observation_confirmed':'物理观测是否确认',
    'selected_targets':'已选目标','count':'目标数量','operation_status':'操作状态','task_result':'任务结果',
    'current_target':'当前目标','target_id':'目标标识','slot':'模拟槽位','status':'结果状态',
    'physical_action_confirmed':'物理动作是否确认',
}.items():
    if key not in PARAMETERS:parameter(key,label,'原始结果字段，保留生产者声明和原始数据值。')


# Validation constraints implemented in __post_init__ but absent from JSON schema.
BOUNDS = {
    'basic.': {'arrival_margin_m': dict(minimum=.1,maximum=.75), 'height_m':dict(exclusiveMinimum=0,maximum=2),
               'duration_ns':dict(exclusiveMinimum=0,maximum=45_000_000_000), 'timeout_ns':dict(exclusiveMinimum=0,maximum=45_000_000_000)},
    'cuadc.': {'altitude_m':dict(minimum=0,maximum=2), 'timeout_ns':dict(minimum=5_000_000_000,maximum=60_000_000_000)},
    'navigation.follow_path': {'timeout_ns':dict(minimum=1_000_000_000,maximum=70_000_000_000)},
    'scenario.maneuver': {'timeout_ns':dict(exclusiveMinimum=0,maximum=300_000_000_000),
        'speed_mps':dict(exclusiveMinimum=0,maximum=.18), 'duration_s':dict(minimum=0,maximum=30),
        'turn_rad':dict(minimum=-18.84955592153876,maximum=18.84955592153876)},
}


def presentation(metadata, *, override=None):
    name=metadata['name']; record=ACTION_TEXT.get(name)
    category,zh,en,description=record or ('uncategorized',name,name,metadata['description'] or name)
    managed=metadata['external_lifecycle']=='managed'
    if not record and managed:category='integration'
    simulation_only=True if record else None
    vehicles=metadata['vehicle_types'][:]
    if not vehicles and record:
        vehicles=['rover'] if name in ('scenario.maneuver','navigation.follow_path') else ['copter'] if name in ('basic.takeoff','basic.land') else ['copter','rover']
    params={}
    def walk(schema):
        for key,child in schema.get('properties',{}).items():
            if key in PARAMETERS:params[key]=deepcopy(PARAMETERS[key])
            walk(child)
        for child in schema.get('anyOf',[])+schema.get('prefixItems',[]):walk(child)
        if 'items'in schema:walk(schema['items'])
    walk(metadata['parameters'])
    output_labels={}
    def output_walk(schema):
        if not isinstance(schema,dict):return
        for key,child in schema.get('properties',{}).items():
            if key in PARAMETERS:output_labels[key]=bilingual('车辆类型','Vehicle type') if key=='kind' else deepcopy(PARAMETERS[key]['label'])
            output_walk(child)
        for child in schema.get('anyOf',[]):output_walk(child)
        if 'items'in schema:output_walk(schema['items'])
    output_walk(metadata['output'])
    bounds=next((v for k,v in BOUNDS.items() if name==k or k.endswith('.') and name.startswith(k)),{})
    for key,value in params.items():
        if key in bounds:value['bounds']=deepcopy(bounds[key])
        if value['unit']=='ns':value.update(display_unit='s',display_scale=1e-9)
    tags=[bilingual('仅软件记录','Software records only')] if name.startswith('Sim.') else [bilingual('仅显式仿真装配','Explicit simulation composition only')] if simulation_only else []
    result=dict(category=category,display_name=bilingual(zh,en),description=bilingual(description,metadata['description'] or en),
        parameters=params,output_labels=output_labels,tags=tags,vehicles=vehicles,simulation_only=simulation_only,
        classification_reason=bilingual('未提供分类元数据；保留原始标识并显示在未分类。','No classification metadata; original ID retained.') if category=='uncategorized' else None,
        dependencies=bilingual('已绑定的 ROS 2 / Nav2、地图与新鲜定位，以及受控外部资源证明。','Bound ROS 2 / Nav2, map, fresh pose and verified external resources.') if name=='NavigateToPose' else
                     bilingual('原有执行上下文、能力与安全检查；不随界面分类自动装配。','Existing context, capabilities and safety admission; never installed by the UI.'),
        provider_id='nav2' if name=='NavigateToPose' else 'managed' if managed else 'in_process' if metadata['external_lifecycle']=='typed_only' else 'opaque',
        provider_description=bilingual('进程内动作，执行时重新检查状态和安全条件。','In-process Action; state and safety checked at admission.') if metadata['external_lifecycle']=='typed_only' else
            bilingual('需要原有外部资源绑定或明确的生命周期契约；注册不代表可执行。','Requires the existing verified resource binding or explicit lifecycle contract; registration is not readiness.'))
    if isinstance(override,dict):
        # Trusted presentation extension only; no control/schema keys are accepted.
        for key in ('category','display_name','description','parameters','tags','dependencies'):
            if key in override:result[key]=deepcopy(override[key])
        if result['category'] not in CATEGORIES or result['category'] in ('logic','submission'):result['category']='uncategorized'
        if result['category']!='uncategorized':result['classification_reason']=None
        else:result['classification_reason']=bilingual('未提供有效的动作分类元数据；保留原始标识。','No valid Action category metadata; original ID retained.')
    return result


def catalog_entry(registry, metadata):
    item=deepcopy(metadata)
    item['presentation']=presentation(item,override=getattr(registry.resolve_typed(item['name'],item['version']).factory,'ui_metadata',None))
    return item

# Rescue fields retain the exact registered schema keys.
for _key,_zh,_unit in [
    ('objects','已定位目标集合',''),('target_id','锁定目标标识',''),('producer_id','观测来源标识',''),
    ('label','目标类别',''),('confidence','识别置信度',''),('captured_ns','原始采样时刻','ns'),
    ('clock_domain','采样时钟域',''),('world_generation','世界代际',''),('observation_id','原始观测标识',''),
    ('servo_outputs','已映射的投放通道',''),('channel','投放通道编号',''),('release_pwm','源任务释放值','PWM'),
    ('hold_pwm','源任务保持值','PWM'),('release_target_ey','源虚拟相机纵向对准偏移',''),
    ('first_release_target_ey','第一次投放画面纵向偏移',''),
    ('second_release_target_ey','第二次投放画面纵向偏移',''),
    ('target_altitude_m','下降目标高度','m'),('descend_speed_mps','最大下降速度','m/s'),
    ('final_settle_time_s','最终稳定时间','s'),('alignment_confirmed','对准已确认',''),
    ('target_acquisition_timeout_s','停止下降后的目标重获期限','s'),
    ('min_confidence','最低观测置信度',''),('cluster_radius_m','目标去重半径','m'),
    ('target_count','最多投放目标数',''),('tolerance_xy_m','水平到达容差','m'),
    ('tolerance_z_m','高度到达容差','m'),('settle_s','到达稳定时间','s'),
]:
    if _key not in PARAMETERS:parameter(_key,_zh,'独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。',_unit)
