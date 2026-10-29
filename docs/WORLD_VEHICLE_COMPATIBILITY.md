# World / Vehicle 静态准入规则

本页记录通用出生点检查的配置与限制；`available` 表示允许进入启动前的配置检查，不能代替 Gazebo、SITL、遥测、控制或运动验收。实际组合结果与证据由本轮测试报告和兼容矩阵单独记录。没有因为 World 加载成功而宣称车辆已经通过测试。

`app/simulation/world_spawns.py` 读取 `simulation/scenarios/world_spawns.json`；World 数据只登记地理参考、地面、允许的车型族、受审区域、预设点与跑道条件。模型、传感器、动力学和飞控配置由固定 Vehicle 定义提供，切换 World 不更改它们。World 与车辆模型不通过场景编号互相选择；同一已注册车辆可申请其他准入 World。

当前规则针对 24 个生成式专项 World 的真实 SDF 基础几何。每次检查使用请求的种子和环境参数生成相同 World，读取其 `spherical_coordinates`、有限地面和实际碰撞体。检查 box、cylinder、sphere；模型、link、collision 的旋转和平移会合成为保守世界坐标 AABB。缓存最多保留 64 个 World / 参数 / 种子组合。未经审阅的 include、嵌套模型、坐标 frame、mesh、heightmap 或未知碰撞形式一律阻塞。

| 范围 | Rover / Copter | 常规 Plane | VTOL |
|---|---|---|---|
| R01–R04、R06–R08、C01–C05、C07–C08 | 已登记中央地面区域，仍执行逐点几何检查 | 无已审跑道，阻塞 | 无合格模型/控制 profile，阻塞 |
| R05、C06 | 动态施力目标缺少可信的全程运动包络，阻塞 | 阻塞 | 阻塞 |
| F01–F04、F06、F08 | 已登记中央地面区域 | 有登记跑道，还须校验实际前方净空 | 阻塞 |
| F05、F07 | 可申请中央地面区域 | 桥梁或平台占据跑道前方，阻塞 | 阻塞 |
| 当前 U_ / H_ 上游与历史 World | 尚未登记经过审阅的出生区域，阻塞 | 阻塞 | 阻塞 |

Rover 和 Copter 的中央区域为 `x ∈ [-4,4]`、`y ∈ [-9,9]`，要求车辆完整外接圆位于区域内，也必须位于真实有限地面内。该区域内的实际静态障碍仍会逐点阻止生成；登记区域不豁免碰撞检查。默认预设依次是 `center` `(0,0)`、`north` `(0,3)`、`south` `(0,-3)`、`north-far` `(0,6)`、`south-far` `(0,-6)`。多车应选择不同预设；两车中心距离至少为两个固定 Vehicle 半径之和再加 0.5 米。普通 Plane 应优先选择 0、±6 米的横向间隔；每个候选点仍要通过各自跑道检查，F03 的部分侧方点会因坡道阻塞。

所有车辆均从地面创建。允许输入严格的 `{id: preset_id}` 或 `{x,y,z,heading_deg}`，拒绝任意路径、模型、姿态扩展字段、布尔坐标和非有限数。自定义点必须落在登记区域，不能借任意高度绕过地面检查。`z` 必须等于实际局部支撑面高度加固定 Vehicle 的 `clearance_z`，输入容差 0.02 米；返回值规范到该高度。Rover / Copter 可用任意有限航向。固定翼须与跑道 +X 方向相差不超过 2 度。

`ground_height` 表示基础有限地面高度。局部 `ground_z` 还考虑实际低矮、水平的 road、runway、runway marking 碰撞面，其顶面不得高于基础地面 0.05 米；这些支撑面必须具备符合约束的实际 box 几何。R03/C04 道路为 0.03 米；固定翼 World 的跑道为 0.03 米，中心线标线可达 0.042 米。最终高度只调整模型在 World 的放置位置，不改车辆内部模型参数。

常规 Plane 额外检查前方 300 米、至少 5 米宽、地面以上 3 米高的走廊。走廊必须完整处于实际跑道支撑面内，实际静态障碍不得侵入。桥梁、平台、侧坡、World 后续几何变更不能因已有白名单而跳过检查。这是起始跑道净空检查，不是全航路避障、风包线、起降距离或持续飞行安全认证。

室内 Copter 的地面出生不意味着室内飞行、无 GPS 导航或穿越屋顶已被验证；河流不代表水动力，坡地不代表可通行性认证。后续扩展上游 World 需先完成原始资源与地形/网格碰撞审查，登记可证明的平坦安全区和地理参考，再实现适用于该资源结构的审阅器并做真实仿真；不能只把目录中的 `ready` 或历史 L1/L2 当作出生准入。所有出生检查不持有控制命令端口，也不改变 SEND、Lease、TTL、session、generation 或唯一写入器规则。

接口：`WorldSpawnRegistry(scene_registry=None).describe(scene_id)` 返回 `scene_id`、`geographic_reference`、`extent_m`、`ground_height`、`spawn_presets`、`vehicle_support`、`constraints`。`validate(scene_id, vehicle_definition, spawn=None, *, peers=(), parameters=None, seed=0)` 返回规范的 `{x,y,z,heading_deg,preset_id}`，失败抛出 `ValueError`。`vehicle_definition` 含注册 `id`、车型族 `family` / `kind`、固定 `radius`、`clearance_z`、`height`；`peers` 为已经校验过的 `{spawn,definition}` 列表。返回值不携带模型路径或控制授权。
