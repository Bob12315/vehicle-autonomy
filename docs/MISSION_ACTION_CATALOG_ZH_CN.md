# Mission Studio 动作分类与中文目录

由真实注册函数和独立展示目录自动生成：
`python -m vehicle_autonomy.app.mission_designer.action_catalog_report --output docs/MISSION_ACTION_CATALOG_ZH_CN.md`

源代码中有 52 个明确身份的类型化动作。此表是多个显式装配入口的并集，不是当前后端已经注册或可执行的清单。
审计只提取契约，不启动动作、ROS、外部进程或车辆连接。历史单一安装包布局与安全边界保持不变。
具体页面只展示当前 Registry 中的真实条目；能否配置由实际车型、能力和 Provider 绑定计算，执行仍重新校验控制权、双发送门与安全策略。
没有独立注册的舵机、相机触发或真实视觉检测动作，不能因分类存在就声称具备该能力。软件演示明确标注为软件记录。
外部作业通过 `register_external(registry, name, ...)` 接受部署给定的 ID，没有固定全局名称；这类实际注册会自动归入外部能力，未翻译字段保留原文。

## 注册与装配边界

- 独立车辆控制：`actions.catalog.register_standard`，三车型仿真能力；不赋予实机控制资格。
- 基础/场景/目标动作：Application 的显式仿真环境装配；原始生命周期为 opaque，不能在 Studio 中假定已绑定。
- `navigation.follow_path`：需要已验证的路径源、坐标变换绑定和车辆模型。
- `NavigateToPose`：需要已明确启动和绑定的原生 Nav2、地图、定位及外部资源；未绑定时不可配置。
- `sitl.*`：专用诊断或 Application 装配，不是默认控制入口。
- `Sim.*`：只有显式软件演示注册，不进行真实检测、飞行或载荷动作。

## 分类及中英文名称

| 原始 Action ID | 中文名称 | 英文名称 | 主分类 | 支持车型（展示审计） |
| --- | --- | --- | --- | --- |
| `Arm` | 解锁车辆 | Arm vehicle | 车辆基础控制 | copter, plane, rover |
| `AutoLand` | 固定翼自动着陆 | Fixed-wing autoland | 车辆基础控制 | plane |
| `Disarm` | 锁定车辆 | Disarm vehicle | 车辆基础控制 | copter, plane, rover |
| `Drive` | 受控行驶 | Drive | 运动与导航 | rover |
| `GetVehicleState` | 状态查询 | Read vehicle state | 安全与状态 | copter, plane, rover |
| `Goto` | 前往目标位置 | Go to position | 运动与导航 | copter, rover |
| `Hold` | 保持当前位置 | Hold position | 安全与状态 | copter |
| `Land` | 降落 | Land | 车辆基础控制 | copter |
| `Loiter` | 固定翼盘旋保持 | Fixed-wing loiter | 安全与状态 | plane |
| `NavigateToPose` | 原生导航到位姿 | Navigate to pose with Nav2 | 外部能力 | rover |
| `RTL` | 原生返航 | Native return to launch | 运动与导航 | copter, plane, rover |
| `Rescue.AlignDescend` | 对准并下降 | Align and descend | 运动与导航 | copter |
| `Rescue.CaptureReconView` | 采集侦察区目标 | Capture recon view | 感知与识别 | copter |
| `Rescue.CaptureView` | 采集投放区目标 | Capture drop view | 感知与识别 | copter |
| `Rescue.ConfirmTarget` | 重新确认锁定目标 | Reconfirm selected target | 感知与识别 | copter |
| `Rescue.FuseViews` | 整理观测目标 | Deduplicate observed targets | 数据与计算 | copter |
| `Rescue.Goto` | 救援航点飞行 | Rescue waypoint | 运动与导航 | copter |
| `Rescue.LandingTarget` | 获取降落 H 标记 | Acquire landing marker | 感知与识别 | copter |
| `Rescue.ReleasePayload` | 请求双通道仿真投放 | Request simulated payload release | 设备与执行器 | copter |
| `Rescue.SelectDropTargets` | 选择救援投放目标 | Select rescue targets | 数据与计算 | copter |
| `Rescue.Takeoff` | 救援起飞 | Rescue takeoff | 车辆基础控制 | copter |
| `ReturnHome` | 返回起点 | Return home | 运动与导航 | copter, rover |
| `SetGuidedTarget` | 设置固定翼导航目标 | Set fixed-wing guided target | 运动与导航 | plane |
| `SetMode` | 切换模式 | Switch mode | 车辆基础控制 | copter, plane, rover |
| `SetVelocity` | 持续速度控制 | Set velocity | 运动与导航 | copter |
| `SetYaw` | 设置航向 | Set yaw | 运动与导航 | copter |
| `Sim.ConfirmTarget` | 仿真目标确认 | Confirm simulated target | 感知与识别 | copter |
| `Sim.DetectContainers` | 仿真容器检测记录 | Simulated container detections | 感知与识别 | copter |
| `Sim.ObserveArea` | 仿真区域观测记录 | Simulated area observation | 感知与识别 | copter |
| `Sim.PreflightCheck` | 仿真任务预检 | Simulated preflight check | 安全与状态 | copter |
| `Sim.RecoverLostTarget` | 仿真目标丢失恢复 | Recover simulated lost target | 复合任务能力 | copter |
| `Sim.ReturnAndLand` | 仿真返航降落记录 | Record simulated return and landing | 复合任务能力 | copter |
| `Sim.SelectTargets` | 仿真目标筛选 | Select simulated targets | 数据与计算 | copter |
| `Sim.SimulatedTaskOperation` | 记录模拟任务操作 | Record simulated task operation | 设备与执行器 | copter |
| `Stop` | 停止运动 | Stop motion | 安全与状态 | rover |
| `Takeoff` | 起飞 | Take off | 车辆基础控制 | copter, plane |
| `Turn` | 停车转向 | Turn | 运动与导航 | rover |
| `basic.arm` | 解锁车辆（基础契约） | Basic arm | 车辆基础控制 | copter, rover |
| `basic.disarm` | 锁定车辆（基础契约） | Basic disarm | 车辆基础控制 | copter, rover |
| `basic.goto` | 前往已解析目标（基础契约） | Basic goto | 运动与导航 | copter, rover |
| `basic.hold` | 有限保持当前位置（基础契约） | Basic hold | 安全与状态 | copter, rover |
| `basic.land` | 降落（基础契约） | Basic land | 车辆基础控制 | copter |
| `basic.return_home` | 返回已解析起点（基础契约） | Basic return home | 运动与导航 | copter, rover |
| `basic.stop` | 停止运动（基础契约） | Basic stop | 安全与状态 | copter, rover |
| `basic.takeoff` | 起飞（基础契约） | Basic takeoff | 车辆基础控制 | copter |
| `cuadc.approach_release` | 接近目标并请求仿真载荷执行 | Approach and request simulated release | 复合任务能力 | copter, rover |
| `cuadc.inspect` | 目标巡检 | Inspect target | 复合任务能力 | copter, rover |
| `navigation.follow_path` | 路径跟踪 | Follow path | 运动与导航 | rover |
| `scenario.maneuver` | 车辆机动 | Vehicle maneuver | 运动与导航 | rover |
| `sitl.arm` | 仿真解锁验证 | SITL arm check | 车辆基础控制 | copter, rover |
| `sitl.disarm` | 仿真上锁验证 | SITL disarm check | 车辆基础控制 | copter, rover |
| `sitl.unarmed_mode` | 未解锁模式验证 | Disarmed SITL mode check | 车辆基础控制 | copter, rover |

## 参数中文对照

表中单位均为原始契约单位；纳秒字段在编辑器显示秒并精确换回整数纳秒。其他字段保留原单位和数值。
数值范围、默认值与必填标记来自真实 Schema，并补充已审计的构造器约束；跨字段及条件约束仍由原动作验证。

| 原始字段 | 中文名称 | 原始单位 | 中文说明 |
| --- | --- | --- | --- |
| `alignment_confirmed` | 对准已确认 | — | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `allow_reverse` | 允许倒车 | — | 必须明确允许且受车辆运动学模型限制，不会自动启用倒车。 |
| `allowed_sources` | 允许的目标来源 | — | 只接受这些来源前缀产生的新鲜目标；保留原始字符串。 |
| `altitude_amsl_m` | 目标海拔高度 | m AMSL | 相对平均海平面的绝对海拔；固定翼准入还检查相对起点的 20～140 米范围。 |
| `altitude_m` | 观测目标高度 | m | 仿真目标动作使用的里程计高度，允许 0～2 米。 |
| `armed` | 是否已解锁 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `arrival_margin_m` | 到达位置容差 | m | 基础动作要求 0.1～0.75 米；容差不替代稳定和停止确认。 |
| `base_to_reference_x_m` | 车体到参考点偏移 | m | 车体原点到运动学参考点的 X 方向偏移。 |
| `bbox_area_px` | 像素框面积 | px² | 像素面积，仅作诊断，不能替代物理尺寸排序。 |
| `binding` | 坐标变换绑定 | — | 显式平面变换、误差界限和原点；不自动推断地图变换。 |
| `capabilities` | 模型能力 | — | 模型声明的能力列表，不授予新的控制权限。 |
| `captured_ns` | 原始采样时刻 | ns | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `channel` | 投放通道编号 | — | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `clock_domain` | 采样时钟域 | — | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `cluster_radius_m` | 目标去重半径 | m | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `confidence` | 识别置信度 | — | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `confirmed` | 确认结果 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `context` | 执行上下文 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `count` | 目标数量 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `cross_track_m` | 横向误差界限 | m | 规划绑定允许的横向误差界限。 |
| `current_target` | 当前目标 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `custom_mode_id` | 原生模式编号 | — | 必须与已审计飞控模式名称一致的数字编号。 |
| `descend_speed_mps` | 最大下降速度 | m/s | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `detections` | 检测记录列表 | — | 由声明的软件场景产生的目标记录，不是实时视觉检测结果。 |
| `duration_ns` | 持续时间 | ns | 编辑器显示秒，保存为整数纳秒；不得超过执行超时。 |
| `duration_s` | 持续时间 | s | 有限等待或机动时长；不表示无限期执行。 |
| `end` | 结束位姿 | — | 已批准机动的终止位置与航向。 |
| `environment` | 环境版本引用 | — | 必须引用当前已绑定的环境及其代际；不能自行拼接为有效授权。 |
| `far_m` | 区域远端距离 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `file_sha256` | 路径文件摘要 | — | 已校验路径文件的 SHA-256 摘要，不是任意文件路径。 |
| `final_settle_time_s` | 最终稳定时间 | s | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `first_release_target_ey` | 第一次投放画面纵向偏移 | — | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `footprint_radius_m` | 足迹半径 | m | 合格车辆模型的平面足迹半径。 |
| `frame` | 控制坐标系 | — | odom 表示里程计东北天；base_link 表示车体前左上；其他坐标需显式绑定。 |
| `frame_epoch` | 坐标系代际 | — | 路径使用的明确坐标系代际，必须与运行时一致。 |
| `generation_id` | 代际标识 | — | 防止跨会话复用资源的原始代际标识。 |
| `height_m` | 目标高度 | m | 多旋翼为当前起飞参考的相对爬升高度；固定翼使用独立已审计跑道高度。 |
| `hold_pwm` | 源任务保持值 | PWM | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `home` | 起点参考 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `id` | 标识 | — | 原始对象标识，不做翻译或重命名。 |
| `kind` | 机动类型 | — | 有限行驶、到访、转向、绕圈或等待；不是车辆类型。 |
| `label` | 目标类别 | — | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `latitude_deg` | 目标纬度 | ° | WGS84 纬度，不是局部位置坐标。 |
| `longitude_deg` | 目标经度 | ° | WGS84 经度，不是局部位置坐标。 |
| `lose_on_confirmation` | 确认时模拟丢失 | — | 软件演示分支；不修改真实传感器。 |
| `map_epoch` | 地图代际 | — | 必须匹配当前经过校验的地图代际；过期地图不可执行导航。 |
| `max_speed_mps` | 最大速度 | m/s | 车辆模型声明的最大速度。 |
| `max_x` | 区域最大 X | m | 父区域坐标系内的最大 X 边界。 |
| `max_y` | 区域最大 Y | m | 父区域坐标系内的最大 Y 边界。 |
| `max_yaw_rate_rps` | 最大偏航角速度 | rad/s | 车辆模型声明的最大偏航角速度。 |
| `min_confidence` | 最低观测置信度 | — | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `min_x` | 区域最小 X | m | 父区域坐标系内的最小 X 边界。 |
| `min_y` | 区域最小 Y | m | 父区域坐标系内的最小 Y 边界。 |
| `mission_status` | 任务状态 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `mode` | 飞控模式 | — | 只能选择当前车辆配置已审计的模式；模式生效不代表物理到达。 |
| `model` | 车辆几何模型 | — | 车辆参考点、足迹和能力参数，必须来自合格场景配置。 |
| `model_id` | 模型标识 | — | 合格车辆运动学模型的原始标识。 |
| `motion_effects` | 运动效果集合 | — | 模型允许的原始效果类型。 |
| `name` | 名称 | — | 程序或资源的原始名称，输入值保持不变。 |
| `native_mode` | 原生模式名称 | — | 诊断契约中请求的飞控原生模式名称。 |
| `near_m` | 区域近端距离 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `objects` | 已定位目标集合 | — | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `observation_id` | 原始观测标识 | — | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `operation_status` | 操作状态 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `path` | 机动路径 | — | 已批准的有限路径，场景机动要求 2～4096 个位姿。 |
| `path_clearance_m` | 路径净空 | m | 经过验证的路径与障碍之间的净空。 |
| `payload_id` | 仿真载荷标识 | — | 仅在有对应能力的多旋翼仿真中使用；不是实机执行器凭据。 |
| `physical_action_confirmed` | 物理动作是否确认 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `physical_arrival_claim` | 物理到达声明 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `physical_diameter_m` | 物理直径 | m | 显式声明的物理尺寸，不从像素框直接推断。 |
| `physical_goal_observed` | 已观测物理目标 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `physical_observation_confirmed` | 物理观测是否确认 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `physical_size_source` | 物理尺寸来源 | — | 物理尺寸的原始来源说明，用于可信筛选。 |
| `poses` | 路径位姿序列 | — | 经过资格检查并绑定到里程计坐标的路径位姿。 |
| `position` | 目标位置 | — | 保留父对象声明的坐标系、单位和参考原点。 |
| `producer_id` | 观测来源标识 | — | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `radius_m` | 绕圈半径 | m | 合格绕圈动作使用 1.5～3 米半径。 |
| `read_only` | 只读结果 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `reference_point` | 车辆参考点 | — | 车辆几何与规划共同采用的参考点。 |
| `region` | 目标搜索区域 | — | 明确的里程计矩形区域，包含边界及坐标系。 |
| `release_pwm` | 源任务释放值 | PWM | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `release_target_ey` | 源虚拟相机纵向对准偏移 | — | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `remaining` | 剩余任务数量 | — | 软件库存剩余数量；模拟操作完成才递减。 |
| `request_id` | 路径请求标识 | — | 路径规划请求的原始标识，用于校验来源。 |
| `resource_id` | 资源标识 | — | 当前注册资源的原始标识。 |
| `result` | 动作结果 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `revision` | 修订号 | — | 资源修订号，不能替代代际。 |
| `scores` | 目标评分表 | — | 目标类别和正整数评分，不使用像素面积代替物理尺寸。 |
| `second_release_target_ey` | 第二次投放画面纵向偏移 | — | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `selected_targets` | 已选目标 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `servo_outputs` | 已映射的投放通道 | — | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `settle_s` | 到达稳定时间 | s | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `simulate_target_loss` | 模拟目标丢失 | — | 仅影响软件演示中目标确认的结果。 |
| `simulated_payload_slot` | 模拟任务槽位 | — | 软件计数槽位，不对应真实物理通道。 |
| `simulation` | 软件仿真标记 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `slot` | 模拟槽位 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `source` | 数据来源 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `source_generation` | 数据源代际 | — | 保留路径来源代际，防止复用失效数据。 |
| `speed_mps` | 行驶速度 | m/s | 地面车沿车体前向的线速度；是否允许倒车由动作及车型约束决定。 |
| `start` | 起始位姿 | — | 已批准机动的起始位置与航向。 |
| `status` | 结果状态 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `stop_turn` | 停车转向 | — | 在原动作支持的条件下使用停车转向策略，不绕过车辆几何约束。 |
| `target` | 目标 | — | 按动作契约输入已解析位置或带来源的软件目标对象，不能仅凭名称执行。 |
| `target_acquisition_timeout_s` | 停止下降后的目标重获期限 | s | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `target_altitude_m` | 下降目标高度 | m | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `target_count` | 最多投放目标数 | — | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `target_id` | 目标标识 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `task_result` | 任务结果 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `timeout_ns` | 执行超时时间 | ns | 编辑器显示秒，保存为整数纳秒；必须满足动作自身期限约束。 |
| `tolerance_xy_m` | 水平到达容差 | m | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `tolerance_z_m` | 高度到达容差 | m | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `turn_rad` | 机动转角 | rad | 有限转角；场景机动不超过正负三圈。 |
| `valid` | 记录有效 | — | 表示当前输入记录是否满足其生产者声明，不授予车辆控制权。 |
| `vehicle_kind` | 车辆类型 | — | 基础目标契约支持地面车和多旋翼；起飞和降落仅多旋翼。 |
| `version` | 版本 | — | 明确的原始版本号。 |
| `vx_mps` | X 方向速度 | m/s | 里程计坐标为向东；车体坐标为向前，由坐标系参数决定。 |
| `vy_mps` | Y 方向速度 | m/s | 里程计坐标为向北；车体坐标为向左，由坐标系参数决定。 |
| `vz_mps` | Z 方向速度 | m/s | 里程计及车体约定均为向上。 |
| `world` | 世界状态快照 | — | 原始结果字段，保留生产者声明和原始数据值。 |
| `world_generation` | 世界代际 | — | 独立救援仿真 Action 的显式参数；由原有准入、安全和新鲜观测校验。 |
| `x` | X 分量 | — | 采用父对象定义的单位与坐标系，不隐式进行坐标变换。 |
| `x_m` | X 方向目标位置 | m | 普通前往目标使用里程计东向坐标；原生导航使用已绑定地图的 X 坐标。 |
| `y` | Y 分量 | — | 采用父对象定义的单位与坐标系，不隐式进行坐标变换。 |
| `y_m` | Y 方向目标位置 | m | 普通前往目标使用里程计北向坐标；原生导航使用已绑定地图的 Y 坐标。 |
| `yaw` | 平面航向 | rad | 父位姿坐标系内的平面航向角。 |
| `yaw_rad` | 目标航向角 | rad | 里程计约定东向为零、逆时针为正；原生导航使用绑定地图的偏航角。 |
| `yaw_rate_rad_s` | 转向角速度 | rad/s | 偏航角速度，采用所选坐标系的右手约定。 |
| `z` | Z 分量 | — | 采用父对象定义的单位与坐标系，不隐式进行坐标变换。 |
| `z_m` | 向上目标高度 | m | 里程计东北天坐标的向上分量；地面车只允许零高度。 |

## 逐项契约、来源与输出

### `Arm@1.0.0` — 解锁车辆

请求解锁，并等待命令和请求之后的真实解锁状态确认。

- 实现：`vehicle_autonomy.actions.common.standard.CommonFactory`；参数类型：`vehicle_autonomy.actions.common.standard`。
- 主分类：`vehicle`；支持车型：copter, plane, rover。原始 Registry 车型字段：`['copter', 'plane', 'rover']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['arm']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {},
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "confirmed": {
      "type": "string"
    },
    "physical_arrival_claim": {
      "const": false
    }
  },
  "required": [
    "confirmed",
    "physical_arrival_claim"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `AutoLand@1.0.0` — 固定翼自动着陆

执行已审计的固定翼跑道着陆，观察近地高度、低速稳定和上锁。

- 实现：`vehicle_autonomy.actions.plane.standard.PlaneFactory`；参数类型：`vehicle_autonomy.actions.common.standard`。
- 主分类：`vehicle`；支持车型：plane。原始 Registry 车型字段：`['plane']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['autoland']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {},
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "armed": {
      "type": "boolean"
    },
    "physical_goal_observed": {
      "const": true
    }
  },
  "required": [
    "physical_goal_observed",
    "armed"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Disarm@1.0.0` — 锁定车辆

请求上锁；飞行器必须符合实测静止地面条件，禁止空中上锁。

- 实现：`vehicle_autonomy.actions.common.standard.CommonFactory`；参数类型：`vehicle_autonomy.actions.common.standard`。
- 主分类：`vehicle`；支持车型：copter, plane, rover。原始 Registry 车型字段：`['copter', 'plane', 'rover']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['disarm']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {},
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "confirmed": {
      "type": "string"
    },
    "physical_arrival_claim": {
      "const": false
    }
  },
  "required": [
    "confirmed",
    "physical_arrival_claim"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Drive@1.0.0` — 受控行驶

持续发送地面车车体前向速度和转向角速度；取消后等待保持模式与停车确认。

- 实现：`vehicle_autonomy.actions.rover.standard.RoverStreamFactory`；参数类型：`vehicle_autonomy.actions.rover.standard`。
- 主分类：`navigation`；支持车型：rover。原始 Registry 车型字段：`['rover']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['drive']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "speed_mps": {
      "type": "number",
      "minimum": -0.5,
      "maximum": 0.5,
      "default": 0.3
    },
    "yaw_rate_rad_s": {
      "type": "number",
      "minimum": -0.35,
      "maximum": 0.35,
      "default": 0.0
    }
  },
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "type": "null"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `GetVehicleState@1.0.0` — 状态查询

读取不可变世界状态、采样时间和新鲜度；不授予车辆控制权。

- 实现：`vehicle_autonomy.actions.common.standard.QueryFactory`；参数类型：`vehicle_autonomy.actions.common.standard`。
- 主分类：`safety`；支持车型：copter, plane, rover。原始 Registry 车型字段：`['copter', 'plane', 'rover']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['state']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {},
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "context": {
      "anyOf": [
        {
          "type": "object"
        },
        {
          "type": "null"
        }
      ]
    },
    "home": {
      "anyOf": [
        {
          "type": "object"
        },
        {
          "type": "null"
        }
      ]
    },
    "kind": {
      "enum": [
        "copter",
        "plane",
        "rover"
      ]
    },
    "read_only": {
      "const": true
    },
    "target": {
      "type": "string"
    },
    "world": {
      "description": "Immutable WorldSnapshot JSON with source/receive/publish times and quality",
      "type": "object"
    }
  },
  "required": [
    "target",
    "kind",
    "world",
    "home",
    "context",
    "read_only"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Goto@1.0.0` — 前往目标位置

前往里程计东北天坐标位置，等待空间到达、稳定和停止确认；地面车高度固定为零，退出后保持 HOLD，后续运动前需切换 GUIDED。

- 实现：`vehicle_autonomy.actions.catalog.GotoFactory`；参数类型：`vehicle_autonomy.actions.copter.standard`。
- 主分类：`navigation`；支持车型：copter, rover。原始 Registry 车型字段：`['copter', 'rover']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['goto']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "x_m": {
      "type": "number",
      "minimum": -15,
      "maximum": 15
    },
    "y_m": {
      "type": "number",
      "minimum": -15,
      "maximum": 15
    },
    "z_m": {
      "type": "number",
      "minimum": 0,
      "maximum": 2,
      "default": 1.5
    }
  },
  "required": [
    "x_m",
    "y_m"
  ]
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "physical_goal_observed": {
      "const": true
    }
  },
  "required": [
    "physical_goal_observed"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Hold@1.0.0` — 保持当前位置

在引导模式持续保持多旋翼当前位置；取消时遵守原有停止屏障。

- 实现：`vehicle_autonomy.actions.common.stream.StreamFactory`；参数类型：`vehicle_autonomy.actions.common.standard`。
- 主分类：`safety`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['hold']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {},
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "type": "null"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Land@1.0.0` — 降落

多旋翼降落，并等待落地、上锁和稳定状态确认。

- 实现：`vehicle_autonomy.actions.copter.standard.BasicFactory`；参数类型：`vehicle_autonomy.actions.common.standard`。
- 主分类：`vehicle`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['land']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {},
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "physical_goal_observed": {
      "const": true
    }
  },
  "required": [
    "physical_goal_observed"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Loiter@1.0.0` — 固定翼盘旋保持

请求固定翼盘旋模式；固定翼保持飞行速度，此操作不是悬停。

- 实现：`vehicle_autonomy.actions.plane.standard.PlaneFactory`；参数类型：`vehicle_autonomy.actions.common.standard`。
- 主分类：`safety`；支持车型：plane。原始 Registry 车型字段：`['plane']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['loiter']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {},
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "confirmed": {
      "type": "string"
    },
    "physical_arrival_claim": {
      "const": false
    }
  },
  "required": [
    "confirmed",
    "physical_arrival_claim"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `NavigateToPose@1.0.0` — 原生导航到位姿

调用原生 Nav2，结合独立新鲜地图位姿、导航生产者退出和车辆停车验证完成。

- 实现：`vehicle_autonomy.actions.navigation.native_rover.NativeRoverNavigationFactory`；参数类型：`vehicle_autonomy.actions.navigation.native_rover`。
- 主分类：`integration`；支持车型：rover。原始 Registry 车型字段：`['rover']`（空列表不代表已验证全部车型）。
- 生命周期：`managed`；所需能力：`[]`。
- 依赖及限制：已绑定的 ROS 2 / Nav2、地图与新鲜定位，以及受控外部资源证明。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "x_m": {
      "type": "number",
      "minimum": -5.0,
      "maximum": 5.0
    },
    "y_m": {
      "type": "number",
      "minimum": -5.0,
      "maximum": 5.0
    },
    "map_epoch": {
      "type": "string",
      "minLength": 1,
      "maxLength": 256
    },
    "yaw_rad": {
      "type": "number",
      "minimum": -3.141592653589793,
      "maximum": 3.141592653589793,
      "default": 0.0
    }
  },
  "required": [
    "x_m",
    "y_m",
    "map_epoch"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `RTL@1.0.0` — 原生返航

地面车和多旋翼按物理返航条件完成；固定翼只确认原生返航模式，不能声称抵达或着陆。

- 实现：`vehicle_autonomy.actions.catalog.register_standard.<locals>.RtlFactory`；参数类型：`vehicle_autonomy.actions.common.standard`。
- 主分类：`navigation`；支持车型：copter, plane, rover。原始 Registry 车型字段：`['copter', 'plane', 'rover']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['rtl']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {},
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "anyOf": [
    {
      "additionalProperties": false,
      "properties": {
        "confirmed": {
          "type": "string"
        },
        "physical_arrival_claim": {
          "const": false
        }
      },
      "required": [
        "confirmed",
        "physical_arrival_claim"
      ],
      "type": "object"
    },
    {
      "additionalProperties": false,
      "properties": {
        "armed": {
          "type": "boolean"
        },
        "physical_goal_observed": {
          "const": true
        }
      },
      "required": [
        "physical_goal_observed",
        "armed"
      ],
      "type": "object"
    }
  ]
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Rescue.AlignDescend@1.0.0` — 对准并下降

读取锁定视觉目标，在对准窗口内下降；丢失时立即请求零速度并限时重获，超时失败，退出经过原有停止屏障。

- 实现：`vehicle_autonomy.actions.composite.rescue.AlignFactory`；参数类型：`vehicle_autonomy.actions.composite.rescue`。
- 主分类：`navigation`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['rescue_flight', 'rescue_vision']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "target": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "target_id": {
          "type": "string"
        },
        "producer_id": {
          "type": "string"
        },
        "label": {
          "type": "string"
        },
        "x_m": {
          "type": "number"
        },
        "y_m": {
          "type": "number"
        },
        "z_m": {
          "type": "number"
        },
        "confidence": {
          "type": "number"
        },
        "captured_ns": {
          "type": "integer"
        },
        "clock_domain": {
          "type": "string"
        },
        "world_generation": {
          "type": "string"
        },
        "observation_id": {
          "type": "string"
        }
      },
      "required": [
        "target_id",
        "producer_id",
        "label",
        "x_m",
        "y_m",
        "z_m",
        "confidence",
        "captured_ns",
        "clock_domain",
        "world_generation",
        "observation_id"
      ]
    },
    "target_altitude_m": {
      "type": "number",
      "minimum": 0.3,
      "maximum": 2.5,
      "default": 1.1
    },
    "descend_speed_mps": {
      "type": "number",
      "minimum": 0.05,
      "maximum": 0.2,
      "default": 0.2
    },
    "release_target_ey": {
      "type": "number",
      "minimum": -1,
      "maximum": 1,
      "default": 0.0
    },
    "final_settle_time_s": {
      "type": "number",
      "minimum": 0.3,
      "maximum": 2,
      "default": 0.3
    },
    "target_acquisition_timeout_s": {
      "type": "number",
      "minimum": 0.5,
      "maximum": 5,
      "default": 3.0
    }
  },
  "required": [
    "target"
  ]
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "alignment_confirmed": {
      "type": "boolean"
    },
    "target_id": {
      "type": "string"
    }
  },
  "required": [
    "alignment_confirmed",
    "target_id"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Rescue.CaptureReconView@1.0.0` — 采集侦察区目标

读取 56/59 米区域的新鲜 PT 目标观测，用于任务结果记录。

- 实现：`vehicle_autonomy.actions.composite.rescue.QueryFactory`；参数类型：`vehicle_autonomy.actions.composite.rescue`。
- 主分类：`perception`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['rescue_vision']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "min_confidence": {
      "type": "number",
      "minimum": 0.3,
      "maximum": 1,
      "default": 0.3
    }
  },
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "objects": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "captured_ns": {
            "type": "integer"
          },
          "clock_domain": {
            "type": "string"
          },
          "confidence": {
            "type": "number"
          },
          "label": {
            "type": "string"
          },
          "observation_id": {
            "type": "string"
          },
          "producer_id": {
            "type": "string"
          },
          "target_id": {
            "type": "string"
          },
          "world_generation": {
            "type": "string"
          },
          "x_m": {
            "type": "number"
          },
          "y_m": {
            "type": "number"
          },
          "z_m": {
            "type": "number"
          }
        },
        "required": [
          "target_id",
          "producer_id",
          "label",
          "x_m",
          "y_m",
          "z_m",
          "confidence",
          "captured_ns",
          "clock_domain",
          "world_generation",
          "observation_id"
        ],
        "type": "object"
      },
      "maxItems": 128,
      "type": "array"
    }
  },
  "required": [
    "objects"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Rescue.CaptureView@1.0.0` — 采集投放区目标

读取本机 PT 识别器发布的新鲜已定位桶观测；不使用地图真值标签。

- 实现：`vehicle_autonomy.actions.composite.rescue.QueryFactory`；参数类型：`vehicle_autonomy.actions.composite.rescue`。
- 主分类：`perception`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['rescue_vision']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "min_confidence": {
      "type": "number",
      "minimum": 0.3,
      "maximum": 1,
      "default": 0.3
    }
  },
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "objects": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "captured_ns": {
            "type": "integer"
          },
          "clock_domain": {
            "type": "string"
          },
          "confidence": {
            "type": "number"
          },
          "label": {
            "type": "string"
          },
          "observation_id": {
            "type": "string"
          },
          "producer_id": {
            "type": "string"
          },
          "target_id": {
            "type": "string"
          },
          "world_generation": {
            "type": "string"
          },
          "x_m": {
            "type": "number"
          },
          "y_m": {
            "type": "number"
          },
          "z_m": {
            "type": "number"
          }
        },
        "required": [
          "target_id",
          "producer_id",
          "label",
          "x_m",
          "y_m",
          "z_m",
          "confidence",
          "captured_ns",
          "clock_domain",
          "world_generation",
          "observation_id"
        ],
        "type": "object"
      },
      "maxItems": 128,
      "type": "array"
    }
  },
  "required": [
    "objects"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Rescue.ConfirmTarget@1.0.0` — 重新确认锁定目标

接近后仅在同一来源、同一类别、原位置附近唯一新鲜观测匹配时重新确认；缺失或歧义时失败。

- 实现：`vehicle_autonomy.actions.composite.rescue.QueryFactory`；参数类型：`vehicle_autonomy.actions.composite.rescue`。
- 主分类：`perception`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['rescue_vision']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "target": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "target_id": {
          "type": "string"
        },
        "producer_id": {
          "type": "string"
        },
        "label": {
          "type": "string"
        },
        "x_m": {
          "type": "number"
        },
        "y_m": {
          "type": "number"
        },
        "z_m": {
          "type": "number"
        },
        "confidence": {
          "type": "number"
        },
        "captured_ns": {
          "type": "integer"
        },
        "clock_domain": {
          "type": "string"
        },
        "world_generation": {
          "type": "string"
        },
        "observation_id": {
          "type": "string"
        }
      },
      "required": [
        "target_id",
        "producer_id",
        "label",
        "x_m",
        "y_m",
        "z_m",
        "confidence",
        "captured_ns",
        "clock_domain",
        "world_generation",
        "observation_id"
      ]
    }
  },
  "required": [
    "target"
  ]
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "target": {
      "additionalProperties": false,
      "properties": {
        "captured_ns": {
          "type": "integer"
        },
        "clock_domain": {
          "type": "string"
        },
        "confidence": {
          "type": "number"
        },
        "label": {
          "type": "string"
        },
        "observation_id": {
          "type": "string"
        },
        "producer_id": {
          "type": "string"
        },
        "target_id": {
          "type": "string"
        },
        "world_generation": {
          "type": "string"
        },
        "x_m": {
          "type": "number"
        },
        "y_m": {
          "type": "number"
        },
        "z_m": {
          "type": "number"
        }
      },
      "required": [
        "target_id",
        "producer_id",
        "label",
        "x_m",
        "y_m",
        "z_m",
        "confidence",
        "captured_ns",
        "clock_domain",
        "world_generation",
        "observation_id"
      ],
      "type": "object"
    }
  },
  "required": [
    "target"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Rescue.FuseViews@1.0.0` — 整理观测目标

去重已经定位的新鲜目标；不声称完成 GPS 三角定位。

- 实现：`vehicle_autonomy.actions.composite.rescue.QueryFactory`；参数类型：`vehicle_autonomy.actions.composite.rescue`。
- 主分类：`data`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['rescue_vision']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "objects": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "target_id": {
            "type": "string"
          },
          "producer_id": {
            "type": "string"
          },
          "label": {
            "type": "string"
          },
          "x_m": {
            "type": "number"
          },
          "y_m": {
            "type": "number"
          },
          "z_m": {
            "type": "number"
          },
          "confidence": {
            "type": "number"
          },
          "captured_ns": {
            "type": "integer"
          },
          "clock_domain": {
            "type": "string"
          },
          "world_generation": {
            "type": "string"
          },
          "observation_id": {
            "type": "string"
          }
        },
        "required": [
          "target_id",
          "producer_id",
          "label",
          "x_m",
          "y_m",
          "z_m",
          "confidence",
          "captured_ns",
          "clock_domain",
          "world_generation",
          "observation_id"
        ]
      }
    },
    "cluster_radius_m": {
      "type": "number",
      "minimum": 0.1,
      "maximum": 1,
      "default": 0.65
    }
  },
  "required": [
    "objects"
  ]
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "objects": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "captured_ns": {
            "type": "integer"
          },
          "clock_domain": {
            "type": "string"
          },
          "confidence": {
            "type": "number"
          },
          "label": {
            "type": "string"
          },
          "observation_id": {
            "type": "string"
          },
          "producer_id": {
            "type": "string"
          },
          "target_id": {
            "type": "string"
          },
          "world_generation": {
            "type": "string"
          },
          "x_m": {
            "type": "number"
          },
          "y_m": {
            "type": "number"
          },
          "z_m": {
            "type": "number"
          }
        },
        "required": [
          "target_id",
          "producer_id",
          "label",
          "x_m",
          "y_m",
          "z_m",
          "confidence",
          "captured_ns",
          "clock_domain",
          "world_generation",
          "observation_id"
        ],
        "type": "object"
      },
      "maxItems": 128,
      "type": "array"
    }
  },
  "required": [
    "objects"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Rescue.Goto@1.0.0` — 救援航点飞行

在明确绑定的救援 ENU 场地内限速飞行，等待到达、低速稳定和退出停止确认。

- 实现：`vehicle_autonomy.actions.copter.rescue.FlightFactory`；参数类型：`vehicle_autonomy.actions.copter.rescue`。
- 主分类：`navigation`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['rescue_flight']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "x_m": {
      "type": "number",
      "minimum": -5,
      "maximum": 5
    },
    "y_m": {
      "type": "number",
      "minimum": -2,
      "maximum": 62
    },
    "z_m": {
      "type": "number",
      "minimum": 0.3,
      "maximum": 5,
      "default": 3.0
    },
    "speed_mps": {
      "type": "number",
      "exclusiveMinimum": 0,
      "maximum": 10,
      "default": 1.0
    },
    "tolerance_xy_m": {
      "type": "number",
      "minimum": 0.1,
      "maximum": 0.7,
      "default": 0.3
    },
    "tolerance_z_m": {
      "type": "number",
      "minimum": 0.1,
      "maximum": 0.5,
      "default": 0.3
    },
    "settle_s": {
      "type": "number",
      "minimum": 0.3,
      "maximum": 3,
      "default": 1.0
    }
  },
  "required": [
    "x_m",
    "y_m"
  ]
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "physical_goal_observed": {
      "const": true
    }
  },
  "required": [
    "physical_goal_observed"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Rescue.LandingTarget@1.0.0` — 获取降落 H 标记

要求起降区内存在新鲜已定位 H 观测；缺失时失败。

- 实现：`vehicle_autonomy.actions.composite.rescue.QueryFactory`；参数类型：`vehicle_autonomy.actions.composite.rescue`。
- 主分类：`perception`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['rescue_vision']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "min_confidence": {
      "type": "number",
      "minimum": 0.3,
      "maximum": 1,
      "default": 0.3
    }
  },
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "target": {
      "additionalProperties": false,
      "properties": {
        "captured_ns": {
          "type": "integer"
        },
        "clock_domain": {
          "type": "string"
        },
        "confidence": {
          "type": "number"
        },
        "label": {
          "type": "string"
        },
        "observation_id": {
          "type": "string"
        },
        "producer_id": {
          "type": "string"
        },
        "target_id": {
          "type": "string"
        },
        "world_generation": {
          "type": "string"
        },
        "x_m": {
          "type": "number"
        },
        "y_m": {
          "type": "number"
        },
        "z_m": {
          "type": "number"
        }
      },
      "required": [
        "target_id",
        "producer_id",
        "label",
        "x_m",
        "y_m",
        "z_m",
        "confidence",
        "captured_ns",
        "clock_domain",
        "world_generation",
        "observation_id"
      ],
      "type": "object"
    }
  },
  "required": [
    "target"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Rescue.ReleasePayload@1.0.0` — 请求双通道仿真投放

仅将明确的 8/9 通道配置映射至 Gazebo 双瓶脱离；不发送实机 PWM 或新增 MAVLink 写入通路。

- 实现：`vehicle_autonomy.actions.composite.rescue.ReleaseFactory`；参数类型：`vehicle_autonomy.actions.composite.rescue`。
- 主分类：`actuation`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['rescue_payload']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "target": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "target_id": {
          "type": "string"
        },
        "producer_id": {
          "type": "string"
        },
        "label": {
          "type": "string"
        },
        "x_m": {
          "type": "number"
        },
        "y_m": {
          "type": "number"
        },
        "z_m": {
          "type": "number"
        },
        "confidence": {
          "type": "number"
        },
        "captured_ns": {
          "type": "integer"
        },
        "clock_domain": {
          "type": "string"
        },
        "world_generation": {
          "type": "string"
        },
        "observation_id": {
          "type": "string"
        }
      },
      "required": [
        "target_id",
        "producer_id",
        "label",
        "x_m",
        "y_m",
        "z_m",
        "confidence",
        "captured_ns",
        "clock_domain",
        "world_generation",
        "observation_id"
      ]
    },
    "servo_outputs": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "channel": {
            "type": "integer"
          },
          "release_pwm": {
            "type": "integer"
          },
          "hold_pwm": {
            "type": "integer"
          }
        },
        "required": [
          "channel",
          "release_pwm",
          "hold_pwm"
        ]
      },
      "minItems": 1,
      "maxItems": 2
    },
    "alignment_confirmed": {
      "type": "boolean",
      "default": false
    },
    "release_target_ey": {
      "type": "number",
      "minimum": -1,
      "maximum": 1,
      "default": 0.0
    }
  },
  "required": [
    "target",
    "servo_outputs"
  ]
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "release_observed": {
      "type": "boolean"
    }
  },
  "required": [
    "release_observed"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Rescue.SelectDropTargets@1.0.0` — 选择救援投放目标

最多选择两个已观测目标；一个桶接收双载荷，两个桶各接收一个。

- 实现：`vehicle_autonomy.actions.composite.rescue.QueryFactory`；参数类型：`vehicle_autonomy.actions.composite.rescue`。
- 主分类：`data`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['rescue_vision']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "objects": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "target_id": {
            "type": "string"
          },
          "producer_id": {
            "type": "string"
          },
          "label": {
            "type": "string"
          },
          "x_m": {
            "type": "number"
          },
          "y_m": {
            "type": "number"
          },
          "z_m": {
            "type": "number"
          },
          "confidence": {
            "type": "number"
          },
          "captured_ns": {
            "type": "integer"
          },
          "clock_domain": {
            "type": "string"
          },
          "world_generation": {
            "type": "string"
          },
          "observation_id": {
            "type": "string"
          }
        },
        "required": [
          "target_id",
          "producer_id",
          "label",
          "x_m",
          "y_m",
          "z_m",
          "confidence",
          "captured_ns",
          "clock_domain",
          "world_generation",
          "observation_id"
        ]
      }
    },
    "target_count": {
      "type": "integer",
      "minimum": 1,
      "maximum": 2,
      "default": 2
    },
    "first_release_target_ey": {
      "type": "number",
      "minimum": -1,
      "maximum": 1,
      "default": 0.3
    },
    "second_release_target_ey": {
      "type": "number",
      "minimum": -1,
      "maximum": 1,
      "default": -0.05
    }
  },
  "required": [
    "objects"
  ]
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "count": {
      "type": "integer"
    },
    "targets": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "release_target_ey": {
            "type": "number"
          },
          "servo_outputs": {
            "items": {
              "additionalProperties": false,
              "properties": {
                "channel": {
                  "type": "integer"
                },
                "hold_pwm": {
                  "type": "integer"
                },
                "release_pwm": {
                  "type": "integer"
                }
              },
              "required": [
                "channel",
                "release_pwm",
                "hold_pwm"
              ],
              "type": "object"
            },
            "type": "array"
          },
          "target": {
            "additionalProperties": false,
            "properties": {
              "captured_ns": {
                "type": "integer"
              },
              "clock_domain": {
                "type": "string"
              },
              "confidence": {
                "type": "number"
              },
              "label": {
                "type": "string"
              },
              "observation_id": {
                "type": "string"
              },
              "producer_id": {
                "type": "string"
              },
              "target_id": {
                "type": "string"
              },
              "world_generation": {
                "type": "string"
              },
              "x_m": {
                "type": "number"
              },
              "y_m": {
                "type": "number"
              },
              "z_m": {
                "type": "number"
              }
            },
            "required": [
              "target_id",
              "producer_id",
              "label",
              "x_m",
              "y_m",
              "z_m",
              "confidence",
              "captured_ns",
              "clock_domain",
              "world_generation",
              "observation_id"
            ],
            "type": "object"
          }
        },
        "required": [
          "target",
          "servo_outputs",
          "release_target_ey"
        ],
        "type": "object"
      },
      "maxItems": 2,
      "type": "array"
    }
  },
  "required": [
    "targets",
    "count"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Rescue.Takeoff@1.0.0` — 救援起飞

独立救援仿真配置内起飞至 4.5 米；仍须经过原有发送门和物理高度确认。

- 实现：`vehicle_autonomy.actions.copter.rescue.FlightFactory`；参数类型：`vehicle_autonomy.actions.copter.rescue`。
- 主分类：`vehicle`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['rescue_flight']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "height_m": {
      "type": "number",
      "exclusiveMinimum": 0,
      "maximum": 5,
      "default": 4.5
    }
  },
  "required": []
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `ReturnHome@1.0.0` — 返回起点

地面车观察回到起点并停车；多旋翼观察返航落地并上锁。

- 实现：`vehicle_autonomy.actions.catalog.ReturnFactory`；参数类型：`vehicle_autonomy.actions.common.standard`。
- 主分类：`navigation`；支持车型：copter, rover。原始 Registry 车型字段：`['copter', 'rover']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['return_home']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {},
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "armed": {
      "type": "boolean"
    },
    "physical_goal_observed": {
      "const": true
    }
  },
  "required": [
    "physical_goal_observed",
    "armed"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `SetGuidedTarget@1.0.0` — 设置固定翼导航目标

配置固定翼经纬度及海拔目标；仅确认配置，不确认到达。飞行状态需满足准入条件。

- 实现：`vehicle_autonomy.actions.plane.standard.PlaneFactory`；参数类型：`vehicle_autonomy.actions.plane.standard`。
- 主分类：`navigation`；支持车型：plane。原始 Registry 车型字段：`['plane']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['guided_target']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "latitude_deg": {
      "type": "number",
      "minimum": -90,
      "maximum": 90
    },
    "longitude_deg": {
      "type": "number",
      "minimum": -180,
      "maximum": 180
    },
    "altitude_amsl_m": {
      "type": "number",
      "description": "Explicit AMSL metres; audited 20..140 m above home"
    }
  },
  "required": [
    "latitude_deg",
    "longitude_deg",
    "altitude_amsl_m"
  ]
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "confirmed": {
      "type": "string"
    },
    "physical_arrival_claim": {
      "const": false
    }
  },
  "required": [
    "confirmed",
    "physical_arrival_claim"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `SetMode@1.0.0` — 切换模式

切换当前车辆已审计模式；模式生效不代表已抵达目标。

- 实现：`vehicle_autonomy.actions.common.standard.CommonFactory`；参数类型：`vehicle_autonomy.actions.common.standard`。
- 主分类：`vehicle`；支持车型：copter, plane, rover。原始 Registry 车型字段：`['copter', 'plane', 'rover']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['mode']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "mode": {
      "type": "string",
      "minLength": 1,
      "maxLength": 20
    }
  },
  "required": [
    "mode"
  ]
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "confirmed": {
      "type": "string"
    },
    "physical_arrival_claim": {
      "const": false
    }
  },
  "required": [
    "confirmed",
    "physical_arrival_claim"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `SetVelocity@1.0.0` — 持续速度控制

在里程计东北天或车体前左上坐标系持续给定多旋翼速度；必须显式取消并确认退出。

- 实现：`vehicle_autonomy.actions.common.stream.StreamFactory`；参数类型：`vehicle_autonomy.actions.copter.standard`。
- 主分类：`navigation`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['velocity']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "vx_mps": {
      "type": "number",
      "minimum": -0.5,
      "maximum": 0.5,
      "default": 0.0
    },
    "vy_mps": {
      "type": "number",
      "minimum": -0.5,
      "maximum": 0.5,
      "default": 0.0
    },
    "vz_mps": {
      "type": "number",
      "minimum": -0.3,
      "maximum": 0.3,
      "default": 0.0
    },
    "yaw_rate_rad_s": {
      "type": "number",
      "minimum": -0.35,
      "maximum": 0.35,
      "default": 0.0
    },
    "frame": {
      "enum": [
        "odom",
        "base_link"
      ],
      "description": "odom ENU or body-relative base_link FLU; SI units",
      "default": "odom"
    }
  },
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "type": "null"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `SetYaw@1.0.0` — 设置航向

将多旋翼里程计航向调整到指定弧度角，并确认角度稳定。

- 实现：`vehicle_autonomy.actions.common.stream.StreamFactory`；参数类型：`vehicle_autonomy.actions.copter.standard`。
- 主分类：`navigation`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['yaw']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "yaw_rad": {
      "type": "number",
      "minimum": -3.141592653589793,
      "maximum": 3.141592653589793
    }
  },
  "required": [
    "yaw_rad"
  ]
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "yaw_rad": {
      "maximum": 3.141592653589793,
      "minimum": -3.141592653589793,
      "type": "number"
    }
  },
  "required": [
    "yaw_rad"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Sim.ConfirmTarget@1.0.0` — 仿真目标确认

验证当前软件目标是否有效；可触发软件目标丢失恢复。

- 实现：`vehicle_autonomy.actions.simulation.studio_demo.DemoFactory`；参数类型：`vehicle_autonomy.actions.simulation.studio_demo`。
- 主分类：`perception`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`[]`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "target": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "id": {
          "type": "string"
        },
        "physical_diameter_m": {
          "type": "number"
        },
        "physical_size_source": {
          "type": "string"
        },
        "bbox_area_px": {
          "type": "integer"
        },
        "valid": {
          "type": "boolean"
        },
        "lose_on_confirmation": {
          "type": "boolean"
        }
      },
      "required": [
        "id",
        "physical_diameter_m",
        "physical_size_source",
        "bbox_area_px",
        "valid",
        "lose_on_confirmation"
      ]
    },
    "simulated_payload_slot": {
      "type": "integer"
    },
    "remaining": {
      "type": "integer"
    }
  },
  "required": [
    "target",
    "simulated_payload_slot",
    "remaining"
  ]
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "confirmed": {
      "type": "boolean"
    },
    "target": {
      "additionalProperties": false,
      "properties": {
        "bbox_area_px": {
          "type": "integer"
        },
        "id": {
          "type": "string"
        },
        "lose_on_confirmation": {
          "type": "boolean"
        },
        "physical_diameter_m": {
          "type": "number"
        },
        "physical_size_source": {
          "type": "string"
        },
        "valid": {
          "type": "boolean"
        }
      },
      "required": [
        "id",
        "physical_diameter_m",
        "physical_size_source",
        "bbox_area_px",
        "valid",
        "lose_on_confirmation"
      ],
      "type": "object"
    }
  },
  "required": [
    "target",
    "confirmed"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Sim.DetectContainers@1.0.0` — 仿真容器检测记录

返回确定性场景目标记录，可模拟丢失；不运行图像检测。

- 实现：`vehicle_autonomy.actions.simulation.studio_demo.DemoFactory`；参数类型：`vehicle_autonomy.actions.simulation.studio_demo`。
- 主分类：`perception`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`[]`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "simulate_target_loss": {
      "type": "boolean",
      "default": false
    }
  },
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "detections": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "bbox_area_px": {
            "type": "integer"
          },
          "id": {
            "type": "string"
          },
          "lose_on_confirmation": {
            "type": "boolean"
          },
          "physical_diameter_m": {
            "type": "number"
          },
          "physical_size_source": {
            "type": "string"
          },
          "valid": {
            "type": "boolean"
          }
        },
        "required": [
          "id",
          "physical_diameter_m",
          "physical_size_source",
          "bbox_area_px",
          "valid",
          "lose_on_confirmation"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "detections"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Sim.ObserveArea@1.0.0` — 仿真区域观测记录

返回声明的软件场景区域，不读取相机，也不进行真实观测。

- 实现：`vehicle_autonomy.actions.simulation.studio_demo.DemoFactory`；参数类型：`vehicle_autonomy.actions.simulation.studio_demo`。
- 主分类：`perception`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`[]`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {},
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "far_m": {
      "type": "number"
    },
    "near_m": {
      "type": "number"
    },
    "physical_observation_confirmed": {
      "type": "boolean"
    },
    "source": {
      "type": "string"
    }
  },
  "required": [
    "near_m",
    "far_m",
    "source",
    "physical_observation_confirmed"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Sim.PreflightCheck@1.0.0` — 仿真任务预检

检查软件演示的任务上下文并生成软件记录；不验证实机适航状态。

- 实现：`vehicle_autonomy.actions.simulation.studio_demo.DemoFactory`；参数类型：`vehicle_autonomy.actions.simulation.studio_demo`。
- 主分类：`safety`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`[]`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {},
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "mission_status": {
      "type": "string"
    },
    "simulation": {
      "type": "boolean"
    }
  },
  "required": [
    "mission_status",
    "simulation"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Sim.RecoverLostTarget@1.0.0` — 仿真目标丢失恢复

记录目标丢失恢复结果，不消耗软件任务槽位；不控制车辆。

- 实现：`vehicle_autonomy.actions.simulation.studio_demo.DemoFactory`；参数类型：`vehicle_autonomy.actions.simulation.studio_demo`。
- 主分类：`composite`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`[]`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "target": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "id": {
          "type": "string"
        },
        "physical_diameter_m": {
          "type": "number"
        },
        "physical_size_source": {
          "type": "string"
        },
        "bbox_area_px": {
          "type": "integer"
        },
        "valid": {
          "type": "boolean"
        },
        "lose_on_confirmation": {
          "type": "boolean"
        }
      },
      "required": [
        "id",
        "physical_diameter_m",
        "physical_size_source",
        "bbox_area_px",
        "valid",
        "lose_on_confirmation"
      ]
    },
    "simulated_payload_slot": {
      "type": "integer"
    },
    "remaining": {
      "type": "integer"
    }
  },
  "required": [
    "target",
    "simulated_payload_slot",
    "remaining"
  ]
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "current_target": {
      "additionalProperties": false,
      "properties": {
        "bbox_area_px": {
          "type": "integer"
        },
        "id": {
          "type": "string"
        },
        "lose_on_confirmation": {
          "type": "boolean"
        },
        "physical_diameter_m": {
          "type": "number"
        },
        "physical_size_source": {
          "type": "string"
        },
        "valid": {
          "type": "boolean"
        }
      },
      "required": [
        "id",
        "physical_diameter_m",
        "physical_size_source",
        "bbox_area_px",
        "valid",
        "lose_on_confirmation"
      ],
      "type": "object"
    },
    "operation_status": {
      "type": "string"
    },
    "remaining": {
      "type": "integer"
    },
    "task_result": {
      "additionalProperties": false,
      "properties": {
        "physical_action_confirmed": {
          "type": "boolean"
        },
        "simulation": {
          "type": "boolean"
        },
        "slot": {
          "type": "integer"
        },
        "status": {
          "type": "string"
        },
        "target_id": {
          "type": "string"
        }
      },
      "required": [
        "target_id",
        "slot",
        "status",
        "simulation",
        "physical_action_confirmed"
      ],
      "type": "object"
    }
  },
  "required": [
    "operation_status",
    "task_result",
    "current_target",
    "remaining"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Sim.ReturnAndLand@1.0.0` — 仿真返航降落记录

仅记录软件任务结束；不会发出返航、起飞或降落命令。

- 实现：`vehicle_autonomy.actions.simulation.studio_demo.DemoFactory`；参数类型：`vehicle_autonomy.actions.simulation.studio_demo`。
- 主分类：`composite`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`[]`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {},
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "mission_status": {
      "type": "string"
    },
    "physical_action_confirmed": {
      "type": "boolean"
    }
  },
  "required": [
    "mission_status",
    "physical_action_confirmed"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Sim.SelectTargets@1.0.0` — 仿真目标筛选

按可信物理尺寸选择两个目标，不以像素框面积代替真实物理大小。

- 实现：`vehicle_autonomy.actions.simulation.studio_demo.DemoFactory`；参数类型：`vehicle_autonomy.actions.simulation.studio_demo`。
- 主分类：`data`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`[]`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "detections": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "id": {
            "type": "string"
          },
          "physical_diameter_m": {
            "type": "number"
          },
          "physical_size_source": {
            "type": "string"
          },
          "bbox_area_px": {
            "type": "integer"
          },
          "valid": {
            "type": "boolean"
          },
          "lose_on_confirmation": {
            "type": "boolean"
          }
        },
        "required": [
          "id",
          "physical_diameter_m",
          "physical_size_source",
          "bbox_area_px",
          "valid",
          "lose_on_confirmation"
        ]
      }
    }
  },
  "required": [
    "detections"
  ]
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "count": {
      "type": "integer"
    },
    "selected_targets": {
      "items": {
        "additionalProperties": false,
        "properties": {
          "bbox_area_px": {
            "type": "integer"
          },
          "id": {
            "type": "string"
          },
          "lose_on_confirmation": {
            "type": "boolean"
          },
          "physical_diameter_m": {
            "type": "number"
          },
          "physical_size_source": {
            "type": "string"
          },
          "valid": {
            "type": "boolean"
          }
        },
        "required": [
          "id",
          "physical_diameter_m",
          "physical_size_source",
          "bbox_area_px",
          "valid",
          "lose_on_confirmation"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "selected_targets",
    "count"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Sim.SimulatedTaskOperation@1.0.0` — 记录模拟任务操作

只更新软件槽位、数量和结果，不操作舵机、相机或物理载荷。

- 实现：`vehicle_autonomy.actions.simulation.studio_demo.DemoFactory`；参数类型：`vehicle_autonomy.actions.simulation.studio_demo`。
- 主分类：`actuation`；支持车型：copter。原始 Registry 车型字段：`['copter']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`[]`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "target": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "id": {
          "type": "string"
        },
        "physical_diameter_m": {
          "type": "number"
        },
        "physical_size_source": {
          "type": "string"
        },
        "bbox_area_px": {
          "type": "integer"
        },
        "valid": {
          "type": "boolean"
        },
        "lose_on_confirmation": {
          "type": "boolean"
        }
      },
      "required": [
        "id",
        "physical_diameter_m",
        "physical_size_source",
        "bbox_area_px",
        "valid",
        "lose_on_confirmation"
      ]
    },
    "simulated_payload_slot": {
      "type": "integer"
    },
    "remaining": {
      "type": "integer"
    }
  },
  "required": [
    "target",
    "simulated_payload_slot",
    "remaining"
  ]
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "current_target": {
      "additionalProperties": false,
      "properties": {
        "bbox_area_px": {
          "type": "integer"
        },
        "id": {
          "type": "string"
        },
        "lose_on_confirmation": {
          "type": "boolean"
        },
        "physical_diameter_m": {
          "type": "number"
        },
        "physical_size_source": {
          "type": "string"
        },
        "valid": {
          "type": "boolean"
        }
      },
      "required": [
        "id",
        "physical_diameter_m",
        "physical_size_source",
        "bbox_area_px",
        "valid",
        "lose_on_confirmation"
      ],
      "type": "object"
    },
    "operation_status": {
      "type": "string"
    },
    "remaining": {
      "type": "integer"
    },
    "task_result": {
      "additionalProperties": false,
      "properties": {
        "physical_action_confirmed": {
          "type": "boolean"
        },
        "simulation": {
          "type": "boolean"
        },
        "slot": {
          "type": "integer"
        },
        "status": {
          "type": "string"
        },
        "target_id": {
          "type": "string"
        }
      },
      "required": [
        "target_id",
        "slot",
        "status",
        "simulation",
        "physical_action_confirmed"
      ],
      "type": "object"
    }
  },
  "required": [
    "operation_status",
    "task_result",
    "current_target",
    "remaining"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Stop@1.0.0` — 停止运动

地面车进入保持模式，并以新鲜遥测确认速度不超过 0.1 米/秒、稳定 2 秒。

- 实现：`vehicle_autonomy.actions.rover.standard.RoverStopFactory`；参数类型：`vehicle_autonomy.actions.common.standard`。
- 主分类：`safety`；支持车型：rover。原始 Registry 车型字段：`['rover']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['stop']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {},
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "additionalProperties": false,
  "properties": {
    "physical_goal_observed": {
      "const": true
    }
  },
  "required": [
    "physical_goal_observed"
  ],
  "type": "object"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Takeoff@1.0.0` — 起飞

多旋翼按目标高度起飞；固定翼只支持已审计的 50 米跑道起飞配置。

- 实现：`vehicle_autonomy.actions.catalog.TakeoffFactory`；参数类型：`vehicle_autonomy.actions.copter.standard`。
- 主分类：`vehicle`；支持车型：copter, plane。原始 Registry 车型字段：`['copter', 'plane']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['takeoff']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "height_m": {
      "type": "number",
      "exclusiveMinimum": 0,
      "maximum": 50,
      "default": 1.5
    }
  },
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "anyOf": [
    {
      "additionalProperties": false,
      "properties": {
        "physical_goal_observed": {
          "const": true
        }
      },
      "required": [
        "physical_goal_observed"
      ],
      "type": "object"
    },
    {
      "additionalProperties": false,
      "properties": {
        "armed": {
          "type": "boolean"
        },
        "physical_goal_observed": {
          "const": true
        }
      },
      "required": [
        "physical_goal_observed",
        "armed"
      ],
      "type": "object"
    }
  ]
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `Turn@1.0.0` — 停车转向

地面车以零线速度和有界偏航角速度转向；实际适用性由已审计驱动配置决定。

- 实现：`vehicle_autonomy.actions.rover.standard.RoverStreamFactory`；参数类型：`vehicle_autonomy.actions.rover.standard`。
- 主分类：`navigation`；支持车型：rover。原始 Registry 车型字段：`['rover']`（空列表不代表已验证全部车型）。
- 生命周期：`typed_only`；所需能力：`['turn']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "yaw_rate_rad_s": {
      "type": "number",
      "minimum": -0.35,
      "maximum": 0.35,
      "default": 0.35
    }
  },
  "required": []
}
```

- 输出结果原始 Schema：

```json
{
  "type": "null"
}
```

输出字段与原契约完全一致，用户变量及引用路径不重命名。

### `basic.arm@1.0.0` — 解锁车辆（基础契约）

早期有限仿真动作契约。需要显式环境版本、车型和合格定位；目标须预先解析，不能与同名独立动作互换。

- 实现：`vehicle_autonomy.actions.common.basic.BasicAction`；参数类型：`vehicle_autonomy.actions.common.basic`。
- 主分类：`vehicle`；支持车型：copter, rover。原始 Registry 车型字段：`[]`（空列表不代表已验证全部车型）。
- 生命周期：`opaque`；所需能力：`['arm']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "vehicle_kind": {
      "type": "string"
    },
    "environment": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "resource_id": {
          "type": "string",
          "minLength": 1
        },
        "version": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "generation_id": {
              "type": "string",
              "minLength": 1
            },
            "revision": {
              "type": "integer"
            }
          },
          "required": [
            "generation_id",
            "revision"
          ]
        }
      },
      "required": [
        "resource_id",
        "version"
      ]
    },
    "target": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "name": {
              "type": "string"
            },
            "frame": {
              "type": "string",
              "minLength": 1
            },
            "position": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "x": {
                  "type": "number"
                },
                "y": {
                  "type": "number"
                },
                "z": {
                  "type": "number"
                }
              },
              "required": [
                "x",
                "y",
                "z"
              ]
            },
            "environment": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "resource_id": {
                  "type": "string",
                  "minLength": 1
                },
                "version": {
                  "type": "object",
                  "additionalProperties": false,
                  "properties": {
                    "generation_id": {
                      "type": "string",
                      "minLength": 1
                    },
                    "revision": {
                      "type": "integer"
                    }
                  },
                  "required": [
                    "generation_id",
                    "revision"
                  ]
                }
              },
              "required": [
                "resource_id",
                "version"
              ]
            }
          },
          "required": [
            "name",
            "frame",
            "position",
            "environment"
          ]
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "arrival_margin_m": {
      "type": "number",
      "default": 0.75
    },
    "height_m": {
      "type": "number",
      "default": 1.5
    },
    "duration_ns": {
      "type": "integer",
      "default": 2000000000
    },
    "timeout_ns": {
      "type": "integer",
      "default": 15000000000
    }
  },
  "required": [
    "vehicle_kind",
    "environment"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `basic.disarm@1.0.0` — 锁定车辆（基础契约）

早期有限仿真动作契约。需要显式环境版本、车型和合格定位；目标须预先解析，不能与同名独立动作互换。

- 实现：`vehicle_autonomy.actions.common.basic.BasicAction`；参数类型：`vehicle_autonomy.actions.common.basic`。
- 主分类：`vehicle`；支持车型：copter, rover。原始 Registry 车型字段：`[]`（空列表不代表已验证全部车型）。
- 生命周期：`opaque`；所需能力：`['disarm']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "vehicle_kind": {
      "type": "string"
    },
    "environment": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "resource_id": {
          "type": "string",
          "minLength": 1
        },
        "version": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "generation_id": {
              "type": "string",
              "minLength": 1
            },
            "revision": {
              "type": "integer"
            }
          },
          "required": [
            "generation_id",
            "revision"
          ]
        }
      },
      "required": [
        "resource_id",
        "version"
      ]
    },
    "target": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "name": {
              "type": "string"
            },
            "frame": {
              "type": "string",
              "minLength": 1
            },
            "position": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "x": {
                  "type": "number"
                },
                "y": {
                  "type": "number"
                },
                "z": {
                  "type": "number"
                }
              },
              "required": [
                "x",
                "y",
                "z"
              ]
            },
            "environment": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "resource_id": {
                  "type": "string",
                  "minLength": 1
                },
                "version": {
                  "type": "object",
                  "additionalProperties": false,
                  "properties": {
                    "generation_id": {
                      "type": "string",
                      "minLength": 1
                    },
                    "revision": {
                      "type": "integer"
                    }
                  },
                  "required": [
                    "generation_id",
                    "revision"
                  ]
                }
              },
              "required": [
                "resource_id",
                "version"
              ]
            }
          },
          "required": [
            "name",
            "frame",
            "position",
            "environment"
          ]
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "arrival_margin_m": {
      "type": "number",
      "default": 0.75
    },
    "height_m": {
      "type": "number",
      "default": 1.5
    },
    "duration_ns": {
      "type": "integer",
      "default": 2000000000
    },
    "timeout_ns": {
      "type": "integer",
      "default": 15000000000
    }
  },
  "required": [
    "vehicle_kind",
    "environment"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `basic.goto@1.0.0` — 前往已解析目标（基础契约）

早期有限仿真动作契约。需要显式环境版本、车型和合格定位；目标须预先解析，不能与同名独立动作互换。

- 实现：`vehicle_autonomy.actions.common.basic.BasicAction`；参数类型：`vehicle_autonomy.actions.common.basic`。
- 主分类：`navigation`；支持车型：copter, rover。原始 Registry 车型字段：`[]`（空列表不代表已验证全部车型）。
- 生命周期：`opaque`；所需能力：`['navigation']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "vehicle_kind": {
      "type": "string"
    },
    "environment": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "resource_id": {
          "type": "string",
          "minLength": 1
        },
        "version": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "generation_id": {
              "type": "string",
              "minLength": 1
            },
            "revision": {
              "type": "integer"
            }
          },
          "required": [
            "generation_id",
            "revision"
          ]
        }
      },
      "required": [
        "resource_id",
        "version"
      ]
    },
    "target": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "name": {
              "type": "string"
            },
            "frame": {
              "type": "string",
              "minLength": 1
            },
            "position": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "x": {
                  "type": "number"
                },
                "y": {
                  "type": "number"
                },
                "z": {
                  "type": "number"
                }
              },
              "required": [
                "x",
                "y",
                "z"
              ]
            },
            "environment": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "resource_id": {
                  "type": "string",
                  "minLength": 1
                },
                "version": {
                  "type": "object",
                  "additionalProperties": false,
                  "properties": {
                    "generation_id": {
                      "type": "string",
                      "minLength": 1
                    },
                    "revision": {
                      "type": "integer"
                    }
                  },
                  "required": [
                    "generation_id",
                    "revision"
                  ]
                }
              },
              "required": [
                "resource_id",
                "version"
              ]
            }
          },
          "required": [
            "name",
            "frame",
            "position",
            "environment"
          ]
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "arrival_margin_m": {
      "type": "number",
      "default": 0.75
    },
    "height_m": {
      "type": "number",
      "default": 1.5
    },
    "duration_ns": {
      "type": "integer",
      "default": 2000000000
    },
    "timeout_ns": {
      "type": "integer",
      "default": 15000000000
    }
  },
  "required": [
    "vehicle_kind",
    "environment"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `basic.hold@1.0.0` — 有限保持当前位置（基础契约）

早期有限仿真动作契约。需要显式环境版本、车型和合格定位；目标须预先解析，不能与同名独立动作互换。

- 实现：`vehicle_autonomy.actions.common.basic.BasicAction`；参数类型：`vehicle_autonomy.actions.common.basic`。
- 主分类：`safety`；支持车型：copter, rover。原始 Registry 车型字段：`[]`（空列表不代表已验证全部车型）。
- 生命周期：`opaque`；所需能力：`['hold']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "vehicle_kind": {
      "type": "string"
    },
    "environment": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "resource_id": {
          "type": "string",
          "minLength": 1
        },
        "version": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "generation_id": {
              "type": "string",
              "minLength": 1
            },
            "revision": {
              "type": "integer"
            }
          },
          "required": [
            "generation_id",
            "revision"
          ]
        }
      },
      "required": [
        "resource_id",
        "version"
      ]
    },
    "target": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "name": {
              "type": "string"
            },
            "frame": {
              "type": "string",
              "minLength": 1
            },
            "position": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "x": {
                  "type": "number"
                },
                "y": {
                  "type": "number"
                },
                "z": {
                  "type": "number"
                }
              },
              "required": [
                "x",
                "y",
                "z"
              ]
            },
            "environment": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "resource_id": {
                  "type": "string",
                  "minLength": 1
                },
                "version": {
                  "type": "object",
                  "additionalProperties": false,
                  "properties": {
                    "generation_id": {
                      "type": "string",
                      "minLength": 1
                    },
                    "revision": {
                      "type": "integer"
                    }
                  },
                  "required": [
                    "generation_id",
                    "revision"
                  ]
                }
              },
              "required": [
                "resource_id",
                "version"
              ]
            }
          },
          "required": [
            "name",
            "frame",
            "position",
            "environment"
          ]
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "arrival_margin_m": {
      "type": "number",
      "default": 0.75
    },
    "height_m": {
      "type": "number",
      "default": 1.5
    },
    "duration_ns": {
      "type": "integer",
      "default": 2000000000
    },
    "timeout_ns": {
      "type": "integer",
      "default": 15000000000
    }
  },
  "required": [
    "vehicle_kind",
    "environment"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `basic.land@1.0.0` — 降落（基础契约）

早期有限仿真动作契约。需要显式环境版本、车型和合格定位；目标须预先解析，不能与同名独立动作互换。

- 实现：`vehicle_autonomy.actions.common.basic.BasicAction`；参数类型：`vehicle_autonomy.actions.common.basic`。
- 主分类：`vehicle`；支持车型：copter。原始 Registry 车型字段：`[]`（空列表不代表已验证全部车型）。
- 生命周期：`opaque`；所需能力：`['land']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "vehicle_kind": {
      "type": "string"
    },
    "environment": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "resource_id": {
          "type": "string",
          "minLength": 1
        },
        "version": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "generation_id": {
              "type": "string",
              "minLength": 1
            },
            "revision": {
              "type": "integer"
            }
          },
          "required": [
            "generation_id",
            "revision"
          ]
        }
      },
      "required": [
        "resource_id",
        "version"
      ]
    },
    "target": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "name": {
              "type": "string"
            },
            "frame": {
              "type": "string",
              "minLength": 1
            },
            "position": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "x": {
                  "type": "number"
                },
                "y": {
                  "type": "number"
                },
                "z": {
                  "type": "number"
                }
              },
              "required": [
                "x",
                "y",
                "z"
              ]
            },
            "environment": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "resource_id": {
                  "type": "string",
                  "minLength": 1
                },
                "version": {
                  "type": "object",
                  "additionalProperties": false,
                  "properties": {
                    "generation_id": {
                      "type": "string",
                      "minLength": 1
                    },
                    "revision": {
                      "type": "integer"
                    }
                  },
                  "required": [
                    "generation_id",
                    "revision"
                  ]
                }
              },
              "required": [
                "resource_id",
                "version"
              ]
            }
          },
          "required": [
            "name",
            "frame",
            "position",
            "environment"
          ]
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "arrival_margin_m": {
      "type": "number",
      "default": 0.75
    },
    "height_m": {
      "type": "number",
      "default": 1.5
    },
    "duration_ns": {
      "type": "integer",
      "default": 2000000000
    },
    "timeout_ns": {
      "type": "integer",
      "default": 15000000000
    }
  },
  "required": [
    "vehicle_kind",
    "environment"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `basic.return_home@1.0.0` — 返回已解析起点（基础契约）

早期有限仿真动作契约。需要显式环境版本、车型和合格定位；目标须预先解析，不能与同名独立动作互换。

- 实现：`vehicle_autonomy.actions.common.basic.BasicAction`；参数类型：`vehicle_autonomy.actions.common.basic`。
- 主分类：`navigation`；支持车型：copter, rover。原始 Registry 车型字段：`[]`（空列表不代表已验证全部车型）。
- 生命周期：`opaque`；所需能力：`['navigation']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "vehicle_kind": {
      "type": "string"
    },
    "environment": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "resource_id": {
          "type": "string",
          "minLength": 1
        },
        "version": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "generation_id": {
              "type": "string",
              "minLength": 1
            },
            "revision": {
              "type": "integer"
            }
          },
          "required": [
            "generation_id",
            "revision"
          ]
        }
      },
      "required": [
        "resource_id",
        "version"
      ]
    },
    "target": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "name": {
              "type": "string"
            },
            "frame": {
              "type": "string",
              "minLength": 1
            },
            "position": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "x": {
                  "type": "number"
                },
                "y": {
                  "type": "number"
                },
                "z": {
                  "type": "number"
                }
              },
              "required": [
                "x",
                "y",
                "z"
              ]
            },
            "environment": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "resource_id": {
                  "type": "string",
                  "minLength": 1
                },
                "version": {
                  "type": "object",
                  "additionalProperties": false,
                  "properties": {
                    "generation_id": {
                      "type": "string",
                      "minLength": 1
                    },
                    "revision": {
                      "type": "integer"
                    }
                  },
                  "required": [
                    "generation_id",
                    "revision"
                  ]
                }
              },
              "required": [
                "resource_id",
                "version"
              ]
            }
          },
          "required": [
            "name",
            "frame",
            "position",
            "environment"
          ]
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "arrival_margin_m": {
      "type": "number",
      "default": 0.75
    },
    "height_m": {
      "type": "number",
      "default": 1.5
    },
    "duration_ns": {
      "type": "integer",
      "default": 2000000000
    },
    "timeout_ns": {
      "type": "integer",
      "default": 15000000000
    }
  },
  "required": [
    "vehicle_kind",
    "environment"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `basic.stop@1.0.0` — 停止运动（基础契约）

早期有限仿真动作契约。需要显式环境版本、车型和合格定位；目标须预先解析，不能与同名独立动作互换。

- 实现：`vehicle_autonomy.actions.common.basic.BasicAction`；参数类型：`vehicle_autonomy.actions.common.basic`。
- 主分类：`safety`；支持车型：copter, rover。原始 Registry 车型字段：`[]`（空列表不代表已验证全部车型）。
- 生命周期：`opaque`；所需能力：`['stop']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "vehicle_kind": {
      "type": "string"
    },
    "environment": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "resource_id": {
          "type": "string",
          "minLength": 1
        },
        "version": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "generation_id": {
              "type": "string",
              "minLength": 1
            },
            "revision": {
              "type": "integer"
            }
          },
          "required": [
            "generation_id",
            "revision"
          ]
        }
      },
      "required": [
        "resource_id",
        "version"
      ]
    },
    "target": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "name": {
              "type": "string"
            },
            "frame": {
              "type": "string",
              "minLength": 1
            },
            "position": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "x": {
                  "type": "number"
                },
                "y": {
                  "type": "number"
                },
                "z": {
                  "type": "number"
                }
              },
              "required": [
                "x",
                "y",
                "z"
              ]
            },
            "environment": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "resource_id": {
                  "type": "string",
                  "minLength": 1
                },
                "version": {
                  "type": "object",
                  "additionalProperties": false,
                  "properties": {
                    "generation_id": {
                      "type": "string",
                      "minLength": 1
                    },
                    "revision": {
                      "type": "integer"
                    }
                  },
                  "required": [
                    "generation_id",
                    "revision"
                  ]
                }
              },
              "required": [
                "resource_id",
                "version"
              ]
            }
          },
          "required": [
            "name",
            "frame",
            "position",
            "environment"
          ]
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "arrival_margin_m": {
      "type": "number",
      "default": 0.75
    },
    "height_m": {
      "type": "number",
      "default": 1.5
    },
    "duration_ns": {
      "type": "integer",
      "default": 2000000000
    },
    "timeout_ns": {
      "type": "integer",
      "default": 15000000000
    }
  },
  "required": [
    "vehicle_kind",
    "environment"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `basic.takeoff@1.0.0` — 起飞（基础契约）

早期有限仿真动作契约。需要显式环境版本、车型和合格定位；目标须预先解析，不能与同名独立动作互换。

- 实现：`vehicle_autonomy.actions.common.basic.BasicAction`；参数类型：`vehicle_autonomy.actions.common.basic`。
- 主分类：`vehicle`；支持车型：copter。原始 Registry 车型字段：`[]`（空列表不代表已验证全部车型）。
- 生命周期：`opaque`；所需能力：`['takeoff']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "vehicle_kind": {
      "type": "string"
    },
    "environment": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "resource_id": {
          "type": "string",
          "minLength": 1
        },
        "version": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "generation_id": {
              "type": "string",
              "minLength": 1
            },
            "revision": {
              "type": "integer"
            }
          },
          "required": [
            "generation_id",
            "revision"
          ]
        }
      },
      "required": [
        "resource_id",
        "version"
      ]
    },
    "target": {
      "anyOf": [
        {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "name": {
              "type": "string"
            },
            "frame": {
              "type": "string",
              "minLength": 1
            },
            "position": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "x": {
                  "type": "number"
                },
                "y": {
                  "type": "number"
                },
                "z": {
                  "type": "number"
                }
              },
              "required": [
                "x",
                "y",
                "z"
              ]
            },
            "environment": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "resource_id": {
                  "type": "string",
                  "minLength": 1
                },
                "version": {
                  "type": "object",
                  "additionalProperties": false,
                  "properties": {
                    "generation_id": {
                      "type": "string",
                      "minLength": 1
                    },
                    "revision": {
                      "type": "integer"
                    }
                  },
                  "required": [
                    "generation_id",
                    "revision"
                  ]
                }
              },
              "required": [
                "resource_id",
                "version"
              ]
            }
          },
          "required": [
            "name",
            "frame",
            "position",
            "environment"
          ]
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "arrival_margin_m": {
      "type": "number",
      "default": 0.75
    },
    "height_m": {
      "type": "number",
      "default": 1.5
    },
    "duration_ns": {
      "type": "integer",
      "default": 2000000000
    },
    "timeout_ns": {
      "type": "integer",
      "default": 15000000000
    }
  },
  "required": [
    "vehicle_kind",
    "environment"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `cuadc.approach_release@1.0.0` — 接近目标并请求仿真载荷执行

接近目标并等待停止，再发出受控载荷效果请求；当前使用仿真载荷确认，不能作为实机执行能力。

- 实现：`vehicle_autonomy.actions.composite.cuadc.TargetAction`；参数类型：`vehicle_autonomy.actions.composite.cuadc`。
- 主分类：`composite`；支持车型：copter, rover。原始 Registry 车型字段：`[]`（空列表不代表已验证全部车型）。
- 生命周期：`opaque`；所需能力：`['navigation', 'payload_release']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "vehicle_kind": {
      "type": "string"
    },
    "environment": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "resource_id": {
          "type": "string",
          "minLength": 1
        },
        "version": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "generation_id": {
              "type": "string",
              "minLength": 1
            },
            "revision": {
              "type": "integer"
            }
          },
          "required": [
            "generation_id",
            "revision"
          ]
        }
      },
      "required": [
        "resource_id",
        "version"
      ]
    },
    "region": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "name": {
          "type": "string"
        },
        "frame": {
          "type": "string",
          "minLength": 1
        },
        "min_x": {
          "type": "number"
        },
        "max_x": {
          "type": "number"
        },
        "min_y": {
          "type": "number"
        },
        "max_y": {
          "type": "number"
        }
      },
      "required": [
        "name",
        "frame",
        "min_x",
        "max_x",
        "min_y",
        "max_y"
      ]
    },
    "altitude_m": {
      "type": "number"
    },
    "payload_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "scores": {
      "type": "array",
      "items": {
        "type": "array",
        "prefixItems": [
          {
            "type": "string"
          },
          {
            "type": "integer"
          }
        ],
        "minItems": 2,
        "maxItems": 2
      },
      "default": [
        [
          "bucket_1",
          500
        ],
        [
          "bucket_2",
          300
        ],
        [
          "bucket_3",
          100
        ]
      ]
    },
    "allowed_sources": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "default": [
        "sim.objects:",
        "vision.recorded:"
      ]
    },
    "timeout_ns": {
      "type": "integer",
      "default": 60000000000
    }
  },
  "required": [
    "vehicle_kind",
    "environment",
    "region",
    "altitude_m"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `cuadc.inspect@1.0.0` — 目标巡检

读取来源白名单中的新鲜目标，按评分选择并接近；不是一个真实视觉检测器。

- 实现：`vehicle_autonomy.actions.composite.cuadc.TargetAction`；参数类型：`vehicle_autonomy.actions.composite.cuadc`。
- 主分类：`composite`；支持车型：copter, rover。原始 Registry 车型字段：`[]`（空列表不代表已验证全部车型）。
- 生命周期：`opaque`；所需能力：`['navigation']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "vehicle_kind": {
      "type": "string"
    },
    "environment": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "resource_id": {
          "type": "string",
          "minLength": 1
        },
        "version": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "generation_id": {
              "type": "string",
              "minLength": 1
            },
            "revision": {
              "type": "integer"
            }
          },
          "required": [
            "generation_id",
            "revision"
          ]
        }
      },
      "required": [
        "resource_id",
        "version"
      ]
    },
    "region": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "name": {
          "type": "string"
        },
        "frame": {
          "type": "string",
          "minLength": 1
        },
        "min_x": {
          "type": "number"
        },
        "max_x": {
          "type": "number"
        },
        "min_y": {
          "type": "number"
        },
        "max_y": {
          "type": "number"
        }
      },
      "required": [
        "name",
        "frame",
        "min_x",
        "max_x",
        "min_y",
        "max_y"
      ]
    },
    "altitude_m": {
      "type": "number"
    },
    "payload_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null
    },
    "scores": {
      "type": "array",
      "items": {
        "type": "array",
        "prefixItems": [
          {
            "type": "string"
          },
          {
            "type": "integer"
          }
        ],
        "minItems": 2,
        "maxItems": 2
      },
      "default": [
        [
          "bucket_1",
          500
        ],
        [
          "bucket_2",
          300
        ],
        [
          "bucket_3",
          100
        ]
      ]
    },
    "allowed_sources": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "default": [
        "sim.objects:",
        "vision.recorded:"
      ]
    },
    "timeout_ns": {
      "type": "integer",
      "default": 60000000000
    }
  },
  "required": [
    "vehicle_kind",
    "environment",
    "region",
    "altitude_m"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `navigation.follow_path@1.0.0` — 路径跟踪

跟踪经过校验并绑定坐标系、地图代际和车辆几何模型的地面车路径。

- 实现：`vehicle_autonomy.actions.navigation.path_following.FollowPathAction`；参数类型：`vehicle_autonomy.actions.navigation.path_following`。
- 主分类：`navigation`；支持车型：rover。原始 Registry 车型字段：`[]`（空列表不代表已验证全部车型）。
- 生命周期：`opaque`；所需能力：`['navigation']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "environment": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "resource_id": {
          "type": "string",
          "minLength": 1
        },
        "version": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "generation_id": {
              "type": "string",
              "minLength": 1
            },
            "revision": {
              "type": "integer"
            }
          },
          "required": [
            "generation_id",
            "revision"
          ]
        }
      },
      "required": [
        "resource_id",
        "version"
      ]
    },
    "request_id": {
      "type": "string"
    },
    "frame_epoch": {
      "type": "string"
    },
    "source_generation": {
      "type": "string"
    },
    "file_sha256": {
      "type": "string"
    },
    "binding": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "x": {
          "type": "number"
        },
        "y": {
          "type": "number"
        },
        "yaw": {
          "type": "number"
        }
      },
      "required": [
        "x",
        "y",
        "yaw"
      ]
    },
    "poses": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "x": {
            "type": "number"
          },
          "y": {
            "type": "number"
          },
          "yaw": {
            "type": "number",
            "default": 0.0
          }
        },
        "required": [
          "x",
          "y"
        ]
      }
    },
    "timeout_ns": {
      "type": "integer",
      "default": 70000000000
    },
    "stop_turn": {
      "type": "boolean",
      "default": false
    },
    "model": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "model_id": {
          "type": "string"
        },
        "revision": {
          "type": "integer"
        },
        "reference_point": {
          "type": "string"
        },
        "base_to_reference_x_m": {
          "type": "number"
        },
        "footprint_radius_m": {
          "type": "number"
        },
        "path_clearance_m": {
          "type": "number"
        },
        "cross_track_m": {
          "type": "number"
        },
        "max_speed_mps": {
          "type": "number"
        },
        "max_yaw_rate_rps": {
          "type": "number"
        },
        "capabilities": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "default": [
            "arm",
            "disarm",
            "hold",
            "navigation",
            "stop"
          ]
        },
        "motion_effects": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "default": [
            "TwistTargetEffect",
            "StopMotionEffect"
          ]
        }
      },
      "required": [
        "model_id",
        "revision",
        "reference_point",
        "base_to_reference_x_m",
        "footprint_radius_m",
        "path_clearance_m",
        "cross_track_m",
        "max_speed_mps",
        "max_yaw_rate_rps"
      ],
      "default": {
        "model_id": "target_rover_front_axle_v1",
        "revision": 1,
        "reference_point": "front_drive_axle",
        "base_to_reference_x_m": 0.25,
        "footprint_radius_m": 0.72,
        "path_clearance_m": 0.95,
        "cross_track_m": 0.15,
        "max_speed_mps": 0.18,
        "max_yaw_rate_rps": 0.25,
        "capabilities": [
          "arm",
          "disarm",
          "hold",
          "navigation",
          "stop"
        ],
        "motion_effects": [
          "TwistTargetEffect",
          "StopMotionEffect"
        ]
      }
    },
    "allow_reverse": {
      "type": "boolean",
      "default": false
    }
  },
  "required": [
    "environment",
    "request_id",
    "frame_epoch",
    "source_generation",
    "file_sha256",
    "binding",
    "poses"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `scenario.maneuver@1.0.0` — 车辆机动

在合格地面车场景中执行有限行驶、到访、转向、绕圈或等待；不是实时避障。

- 实现：`vehicle_autonomy.actions.rover.maneuver.ManeuverAction`；参数类型：`vehicle_autonomy.actions.rover.maneuver`。
- 主分类：`navigation`；支持车型：rover。原始 Registry 车型字段：`[]`（空列表不代表已验证全部车型）。
- 生命周期：`opaque`；所需能力：`['navigation', 'stop']`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "environment": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "resource_id": {
          "type": "string",
          "minLength": 1
        },
        "version": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "generation_id": {
              "type": "string",
              "minLength": 1
            },
            "revision": {
              "type": "integer"
            }
          },
          "required": [
            "generation_id",
            "revision"
          ]
        }
      },
      "required": [
        "resource_id",
        "version"
      ]
    },
    "kind": {
      "type": "string"
    },
    "start": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "x": {
          "type": "number"
        },
        "y": {
          "type": "number"
        },
        "yaw": {
          "type": "number",
          "default": 0.0
        }
      },
      "required": [
        "x",
        "y"
      ]
    },
    "end": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "x": {
          "type": "number"
        },
        "y": {
          "type": "number"
        },
        "yaw": {
          "type": "number",
          "default": 0.0
        }
      },
      "required": [
        "x",
        "y"
      ]
    },
    "path": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "x": {
            "type": "number"
          },
          "y": {
            "type": "number"
          },
          "yaw": {
            "type": "number",
            "default": 0.0
          }
        },
        "required": [
          "x",
          "y"
        ]
      }
    },
    "speed_mps": {
      "type": "number",
      "default": 0.15
    },
    "turn_rad": {
      "type": "number",
      "default": 0.0
    },
    "radius_m": {
      "type": "number",
      "default": 0.0
    },
    "duration_s": {
      "type": "number",
      "default": 0.0
    },
    "timeout_ns": {
      "type": "integer",
      "default": 90000000000
    }
  },
  "required": [
    "environment",
    "kind",
    "start",
    "end",
    "path"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `sitl.arm@1.0.0` — 仿真解锁验证

显式授权的飞控软件仿真解锁步骤，受现有发送门和安全策略限制。

- 实现：`vehicle_autonomy.actions.common.sitl_mode.SitlArmAction`；参数类型：`vehicle_autonomy.actions.common.sitl_mode`。
- 主分类：`vehicle`；支持车型：copter, rover。原始 Registry 车型字段：`[]`（空列表不代表已验证全部车型）。
- 生命周期：`opaque`；所需能力：`[]`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "native_mode": {
      "type": "string"
    },
    "custom_mode_id": {
      "type": "integer"
    }
  },
  "required": [
    "native_mode",
    "custom_mode_id"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `sitl.disarm@1.0.0` — 仿真上锁验证

显式飞控软件仿真上锁步骤，等待原有命令确认。

- 实现：`vehicle_autonomy.actions.common.sitl_mode.SitlDisarmAction`；参数类型：`vehicle_autonomy.actions.common.sitl_mode`。
- 主分类：`vehicle`；支持车型：copter, rover。原始 Registry 车型字段：`[]`（空列表不代表已验证全部车型）。
- 生命周期：`opaque`；所需能力：`[]`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "native_mode": {
      "type": "string"
    },
    "custom_mode_id": {
      "type": "integer"
    }
  },
  "required": [
    "native_mode",
    "custom_mode_id"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

### `sitl.unarmed_mode@1.0.0` — 未解锁模式验证

仅在未解锁飞控软件仿真中验证模式命令和随后状态。

- 实现：`vehicle_autonomy.actions.common.sitl_mode.SitlModeAction`；参数类型：`vehicle_autonomy.actions.common.sitl_mode`。
- 主分类：`vehicle`；支持车型：copter, rover。原始 Registry 车型字段：`[]`（空列表不代表已验证全部车型）。
- 生命周期：`opaque`；所需能力：`[]`。
- 依赖及限制：原有执行上下文、能力与安全检查；不随界面分类自动装配。
- 当前可用性：取决于运行部署，源代码审计不打开连接也不认定就绪。仅显式仿真装配，实机未验收。
- 输入参数原始 Schema（中文说明见前表；此处保留程序字段及单位）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "native_mode": {
      "type": "string"
    },
    "custom_mode_id": {
      "type": "integer"
    }
  },
  "required": [
    "native_mode",
    "custom_mode_id"
  ]
}
```

- 输出结果原始 Schema：

```json
null
```

未声明输出 Schema 时保留为 `null`，不会伪造结构；实际诊断结果不能因此成为可绑定的类型化数据。

## 扩展方式

新增动作仍先通过 Registry 注册。分类和翻译可加入 `action_localization.ACTION_TEXT` / `PARAMETERS`，或在受信任的 factory 上提供 `ui_metadata`（category、display_name、description、parameters、tags、dependencies）。
显示名称和说明使用 `zh-CN` / `en-US` 字典。未提供翻译时回退英文或原始 ID；未提供分类时进入“未分类”并说明原因。不得通过此元数据更改能力、Schema、车辆权限或 Provider 就绪状态。
前端收藏和最近使用仅保存动作 ID 与版本；不保存密钥或任务参数。仅动作库和相关展示提供基础英文切换，其他已有页面仍以中文为主。
底层错误没有准确中文对应时显示原始错误，不生成猜测解释。原始 ID、原始日志和完整诊断始终保留。
