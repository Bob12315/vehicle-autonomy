# Vehicle Autonomy Framework V1：基础合同冻结规范

**状态：FROZEN V1.0**
**冻结日期：2026-09-30**

> **实施状态：P1 合同层、P2 离线状态链、P3 决策链及 P4 假端口控制边界已实现。** 新根目录已有 Typed Effect、版本化快照、Transform 求解器和 `submit/cancel/status` 窄端口；P4 Execution 只接假命令端口，真实设备连接与生产 writer 仍属后续阶段。冻结语义不变；实际范围与测试见 [迁移计划](migration_plan.md)，总体职责见 [V1 目标架构](framework_v1.md)。

本文冻结 Vehicle Autonomy Framework V1 的基础合同。后续 Sensor、Perception、Localization、World Model、Mission、Planning、Guidance、Execution、Vehicle Plugin、Protocol 和 Transport 均建立在本文定义的语义之上。

除非发现基础语义错误，否则后续迁移不得为了兼容旧项目而修改这些合同的核心含义。旧项目与本规范不一致的部分应通过 Adapter 或迁移层兼容，而不是反向污染新合同。

目标架构规定 Observation、WorldSnapshot、Intent 与 Effect 是核心数据边界；VehicleState 是车辆适配器发布的标准状态，VehicleCommand 是经过 Execution、Authorization 和 Safety 后才允许提交给车辆端口的命令。

---

## 1. 基础原则

V1 基础合同遵循以下原则：

1. Core 使用稳定的领域语义，不使用 MAVLink、ROS message、串口或具体硬件协议作为内部合同。
2. 空间数据采用统一的 ROS 风格坐标约定，但允许存在多个参考 Frame。
3. 所有跨 Frame 运算通过统一 Transform 系统完成。
4. 时间事实与动态计算值分离。
5. VehicleState 表示车辆自身报告的状态，不表示自主系统最终认定的世界状态。
6. Localization 独立于 VehicleState。
7. WorldSnapshot 是高级自主模块读取世界状态的唯一稳定入口。
8. Effect 表示“请求产生什么副作用”，VehicleCommand 表示“经过控制边界后准备提交什么命令”。
9. 状态链不得获得车辆命令发送权限。
10. 具体比赛、车辆、协议和设备语义不得写入通用基础合同。

---

# 2. 坐标系与 Frame

## 2.1 Core 统一坐标约定

Core 采用 ROS 风格右手坐标约定。

### 世界 / 局部坐标

采用 ENU：

```text
+x = East
+y = North
+z = Up
```

### 机体坐标

采用 FLU：

```text
+x = Forward
+y = Left
+z = Up
```

### Camera Optical

采用 ROS Optical convention：

```text
+x = Right
+y = Down
+z = Forward
```

### 单位

统一采用 SI：

```text
distance       m
velocity       m/s
acceleration   m/s²
angle          rad
angular rate   rad/s
time duration  s / ns
```

内部姿态统一使用 Quaternion。

Euler Angle 只允许作为输入、显示、配置或临时计算形式，不作为核心姿态存储格式。

---

## 2.2 标准 Frame

V1 预定义常用 Frame 名称：

```text
earth
map
odom
base_link
```

设备按实际装配增加：

```text
camera_down_link
camera_down_optical
lidar_front
imu_link
gimbal_link
...
```

Frame 名称不采用固定 Enum。

基础类型：

```text
FrameId = string identity
```

例如：

```text
FrameId("map")
FrameId("base_link")
FrameId("camera_down_optical")
```

这样未来可以直接扩展多传感器、多车辆和 ROS 2 namespace，而不修改 Core Enum。

---

## 2.3 FIELD 坐标系

原 `cuadc2026` 的比赛专用 FIELD：

```text
+X = 场地右
+Y = 场地前
```

**不迁移到新框架基础合同。**

V1 Core 不定义 `FIELD`。

未来某个具体任务如果需要场景局部坐标，应由对应 Environment / Application 定义普通 Frame 和 Transform，而不是增加 Core 特殊坐标系。

---

## 2.4 ArduPilot / MAVLink 坐标

ArduPilot / MAVLink 的：

```text
LOCAL_NED
BODY_FRD
MAV_FRAME_*
```

全部属于 Vehicle / Protocol Adapter 边界。

不得进入：

```text
Mission
Action
Planning
Guidance
World Model
Localization API
Core Geometry API
```

转换关系至少包括：

### NED → ENU

```text
ENU.x = NED.y
ENU.y = NED.x
ENU.z = -NED.z
```

### FRD → FLU

```text
FLU.x =  FRD.x
FLU.y = -FRD.y
FLU.z = -FRD.z
```

协议坐标必须在进入 Core 前完成标准化。

---

# 3. Geometry 基础合同

V1 冻结以下基础几何类型：

```text
Vector3
Quaternion
Pose3
Twist3
Transform3
GeoPoint
```

### Vector3

```text
x: float
y: float
z: float
```

Vector3 本身不包含坐标语义。

坐标语义由外层 `frame_id` 决定。

### Quaternion

固定字段顺序：

```text
x
y
z
w
```

Quaternion 必须：

- 数值有限；
- 满足允许的归一化误差；
- 不能使用 NaN / Infinity。

### Pose3

```text
position: Vector3
orientation: Quaternion
```

### Twist3

```text
linear: Vector3
angular: Vector3
```

### Transform3

```text
translation: Vector3
rotation: Quaternion
```

表示：

```text
source frame → target frame
```

的刚体变换。

### GeoPoint

```text
latitude_deg
longitude_deg
altitude_m
```

GeoPoint 专门用于地理坐标。

不得使用普通 `Vector3(x, y, z)` 表示经纬度。

---

# 4. Stamped 空间数据

任何具有空间含义的数据必须能够确定：

```text
frame_id
timestamp
```

建议基础形式：

```text
Stamped[T]
├── frame_id
├── captured_at
└── value: T
```

例如：

```text
Stamped[Pose3]
Stamped[Twist3]
Stamped[Vector3]
```

空间数据缺少 `frame_id` 时应视为无效合同输入。

非空间数据可以不带 Frame。

---

# 5. Transform 合同

系统只采用**一套坐标规范**，但允许多个 Frame。

因此原则是：

> 一个坐标规范，多参考系，一个 Transform 系统。

统一 Transform API 必须支持：

```text
point/vector/pose/twist transform
from_frame
to_frame
at_time
```

概念接口：

```text
transform(value, from_frame, to_frame, at_time)
```

---

## 5.1 Static Transform

用于固定安装关系：

```text
base_link
    ↓
camera_down_link
    ↓
camera_down_optical
```

例如摄像头相对机体的位置和安装姿态。

---

## 5.2 Dynamic Transform

用于随时间变化的关系：

```text
odom → base_link
map  → odom
```

动态 Transform 必须具有时间语义。

不能用“当前姿态”转换过去采集的传感器数据。

---

## 5.3 Transform 唯一性

以下行为禁止：

- Action 自己写坐标转换公式；
- Perception 自己复制机体系转换；
- Mission 自己执行 NED/ENU 翻轴；
- Camera 模块自行定义另一套旋转规则。

跨 Frame 变换必须经过统一 Transform Provider / Resolver。

---

# 6. 时间合同

V1 冻结统一时间类型：

```text
TimePoint
├── monotonic_ns
├── utc
└── clock_domain_id
```

### monotonic_ns

用于：

- timeout；
- TTL；
- deadline；
- freshness；
- duration；
- deadman。

只有相同 `clock_domain_id` 的 monotonic 时间才允许直接比较。

### utc

用于：

- 日志；
- 人类查看；
- 跨系统关联；
- 数据记录。

UTC 不作为实时 timeout 的主要依据。

---

## 6.1 三类时间事实

基础合同区分：

### captured_at

数据实际被采样或产生的时间。

### received_at

当前节点收到该数据的时间。

### published_at

一个标准状态或 Snapshot 被系统发布的时间。

三者不得混用。

---

## 6.2 age 不作为原始事实保存

生产者不得保存动态变化的：

```text
age_s
age_ms
```

应保存：

```text
captured_at
received_at
published_at
```

World Model 在生成固定 Snapshot 时可以计算：

```text
age_ns
freshness
```

因为针对一个不可变 Snapshot，该值也是固定事实。

---

# 7. Identity 与 Provenance

原系统：

```text
SourceId = real / sitl / test
```

不进入新的基础状态合同。

真实车辆、SITL、Replay、Fake Test 应通过不同 Adapter 或 Deployment 组合实现。

高级模块不得出现：

```text
if source == "sitl":
    ...
```

---

## 7.1 保留的 Identity

基础合同允许：

```text
VehicleId
SensorId
ProducerId
ObservationId
SnapshotId
EffectId
```

其中 `producer_id` 用于：

- 数据追踪；
- 日志；
- 诊断；
- 融合；
- 回放；
- provenance。

例如：

```text
vehicle_adapter
camera_down
yolo_detector
fast_lio
vins
```

`producer_id` 是来源追踪信息，不是业务逻辑选择开关。

---

# 8. Quality 与 Freshness

质量与新鲜度是两个独立维度。

## 8.1 QualityState

V1：

```text
VALID
DEGRADED
INVALID
UNAVAILABLE
```

语义：

### VALID

数据满足当前用途的正常质量要求。

### DEGRADED

数据仍可使用，但存在已知质量下降。

### INVALID

存在数据，但不能被当前消费者视为有效事实。

### UNAVAILABLE

当前没有相应数据。

---

## 8.2 FreshnessState

V1：

```text
FRESH
STALE
UNKNOWN
```

例如：

```text
quality   = DEGRADED
freshness = FRESH
```

表示：

> 数据刚刚产生，但定位本身质量较差。

因此不得使用一个 `valid: bool` 同时表示质量、新鲜度、连接状态和可用性。

---

# 9. Observation

Observation 是 Sensor、Perception 或其他状态生产者向状态链提供信息的基础合同。

目标架构要求 Observation 带有来源、时间、坐标与质量信息，而且 Observation 本身不能授予控制权。

V1 概念合同：

```text
Observation[T]
│
├── observation_id
├── schema_version
├── producer_id
├── sequence
├── captured_at
├── received_at
├── frame_id?
├── quality
└── data: T
```

其中：

```text
T
```

必须是 Typed Observation Data。

例如未来可以增加：

```text
GpsObservation
ImuObservation
ImageObservation
DetectionObservation
DepthObservation
PointCloudObservation
ObstacleObservation
```

V1 不要求一次实现所有类型。

---

## 9.1 禁止 Any Observation

稳定合同不得定义为：

```text
Observation[dict[str, Any]]
```

或：

```text
data: Mapping[str, Any]
```

长期跨模块合同必须 Typed。

临时 debug metadata 可以使用受限 JSON，但不能承担主要领域语义。

---

# 10. VehicleState

## 10.1 定义

VehicleState 表示：

> Vehicle Adapter 对车辆自身报告状态的标准化结果。

VehicleState 不是：

- World Model；
- 最终 Localization；
- Authorization；
- Safety；
- Execution 状态。

数据关系：

```text
Vehicle / Flight Controller
          ↓
     Vehicle Adapter
          ↓
      VehicleState
          ↓
       World Model
```

目标架构要求车辆适配器提供标准 VehicleState，再由 World Model 消费。

---

## 10.2 VehicleStateSnapshot V1

概念结构：

```text
VehicleStateSnapshot
│
├── schema_version
├── vehicle_id
├── version
├── published_at
│
├── reported_pose?
├── reported_twist?
├── global_position?
├── operation
├── battery?
└── health
```

### reported_pose

表示：

> 车辆 / 飞控自己认为车辆在哪里。

例如当前 ArduPilot：

```text
MAVLink LOCAL_POSITION_NED
       ↓
Vehicle Adapter
       ↓ NED → ENU
VehicleState.reported_pose
```

它不是自主系统最终 Localization 的同义词。

### reported_twist

表示车辆 / 飞控报告的速度与角速度。

### global_position

可包含标准 GeoPoint。

### operation

至少可以表达：

```text
armed
motion_state
failsafe
native_mode
```

车辆类别不支持的字段允许为 `None / UNAVAILABLE`。

### battery

标准化电源状态。

### health

车辆自身健康信息。

---

## 10.3 VehicleState 明确禁止的内容

不得包含：

```text
control_allowed
send_enabled
lease
authorization
action_send
send_generation
```

这些全部属于控制链。

VehicleState 回答：

> 车辆是什么状态？

Authorization 回答：

> 当前控制主体有没有权限？

Safety 回答：

> 这个具体请求是否允许执行？

三者必须严格分离。

---

## 10.4 LinkState

连接状态：

```text
connected
link_session
last_rx
link_health
```

不属于车辆物理状态本身。

V1 将 LinkState 视为独立基础运行状态。

`stale` 也不直接存入 VehicleState 原始数据；World Model 根据时间事实计算 freshness。

---

# 11. LocalizationEstimate

Localization 是 VehicleState 之外的独立状态生产模块。

目标架构允许 Localization 采用 GPS、VIO、SLAM 或融合实现。

概念合同：

```text
LocalizationEstimate
│
├── schema_version
├── version
├── producer_id
├── published_at
│
├── pose
├── twist?
├── covariance?
└── quality
```

其中 Pose / Twist 使用统一 Frame + Time 合同。

---

## 11.1 定位来源

LocalizationEstimate 可以来自：

```text
FlightControllerLocalization
GpsLocalization
VioLocalization
LidarLocalization
FusedLocalization
```

例如当前只有飞控时：

```text
VehicleState.reported_pose
          ↓
FlightControllerLocalization
          ↓
LocalizationEstimate
```

以后加入 LiDAR：

```text
LiDAR + IMU
    ↓
 FAST-LIO
    ↓
LocalizationEstimate
```

Mission 和 Planning 不需要知道当前具体采用哪种算法。

---

## 11.2 三层定位语义冻结

V1 正式冻结：

```text
VehicleState.reported_pose
=
车辆 / 飞控自身报告的位置
```

```text
LocalizationEstimate.pose
=
某个 Localization 实现输出的位置
```

```text
WorldSnapshot.localization.pose
=
当前自主系统最终采用的位置
```

这三者不得在类型或语义上合并。

---

# 12. WorldSnapshot

## 12.1 定义

WorldSnapshot 表示：

> 自主系统在某一确定版本上对当前世界状态的统一认识。

World Model 汇总车辆状态、感知、定位、地图与 Environment，并处理来源、时间、坐标变换、新鲜度和缺失状态。

---

## 12.2 核心性质

WorldSnapshot 必须：

```text
immutable
versioned
traceable
```

发布之后不得原地修改。

Action 一个 tick 内读取的 Snapshot 必须保持一致。

---

## 12.3 WorldSnapshot V1

概念结构：

```text
WorldSnapshot
│
├── snapshot_id
├── version
├── published_at
│
├── vehicle
├── localization
├── objects
├── map?
├── environment?
├── freshness
└── dependencies
```

### vehicle

车辆自身报告的标准 VehicleState。

### localization

系统最终采用的 LocalizationEstimate。

这是 Mission、Planning 和 Guidance 获取自身位置的默认来源。

### objects

World Model 当前认为存在的环境对象。

V1 只冻结容器语义，具体 Object 类型随 Perception 阶段增加。

### map

当前地图引用与版本。

V1 可以为空。

### environment

任务环境静态 / 半静态信息。

V1 可以为空。

### freshness

World Model 在 Snapshot 发布时计算的各组件新鲜度。

### dependencies

记录当前 Snapshot 依赖的输入版本，例如：

```text
VehicleState #891
Localization #327
Detection #1821
Map #12
Environment #4
```

用于：

- replay；
- debug；
- audit；
- deterministic test。

---

## 12.4 WorldSnapshot 明确禁止控制状态

不得包含：

```text
SEND
Action SEND
Lease
Authorization
Cancellation generation
VehicleCommand queue
```

Action 如需运行控制上下文，应通过独立 RuntimeContext 获得。

目标架构要求 Action 读取 WorldSnapshot 和受约束的运行上下文，而不是把所有状态混入 WorldSnapshot。

---

# 13. Typed Effect

## 13.1 定义

Effect 表示：

> 一个已经验证过结构，但尚未获得最终车辆执行授权的副作用请求。

Effect 不是：

- MAVLink message；
- VehicleCommand；
- 已授权发送请求；
- 底层 writer invocation。

目标架构明确规定 Effect 是结构化副作用，不是 MAVLink 包，也不是已经获准的车辆命令。

---

## 13.2 EffectEnvelope

V1：

```text
EffectEnvelope
│
├── schema_version
├── effect_id
├── run_id
├── action_instance_id
├── created_at
├── deadline
└── effect
```

这里统一使用字段名：

```text
effect
```

不使用 `payload`，避免与任务载荷产生歧义。

---

## 13.3 EffectEnvelope 不包含授权信息

不得包含：

```text
authorization_generation
lease_generation
send_generation
expected_link_session_id
```

这些信息在 Effect 产生时尚未完成最终授权。

它们属于 Execution → VehicleCommand 阶段。

---

## 13.4 Vehicle Effect V1

V1 冻结基础类别：

```text
ArmEffect
DisarmEffect
TakeoffEffect
LandEffect
ModeEffect
PoseTargetEffect
TwistTargetEffect
StopMotionEffect
```

后续只在真实需求出现时增加新的 Effect。

---

## 13.5 PoseTargetEffect

概念：

```text
PoseTargetEffect
├── frame_id
├── target_pose
└── constraints?
```

由于 Frame 已经显式存在，因此不再需要分别设计：

```text
LocalPositionEffect
BodyPositionEffect
FieldPositionEffect
```

---

## 13.6 TwistTargetEffect

概念：

```text
TwistTargetEffect
├── frame_id
├── target_twist
└── constraints?
```

例如：

```text
frame_id = base_link

linear:
    x = 1.0
    y = 0.0
    z = 0.0
```

表达：

> 请求车辆沿机头方向前进 1 m/s。

不包含任何 MAVLink Frame ID。

---

## 13.7 One-shot 与 Continuous

Effect 必须能够区分：

```text
ONE_SHOT
CONTINUOUS
```

典型 One-shot：

```text
Arm
Disarm
Takeoff
Land
Mode
```

典型 Continuous：

```text
TwistTarget
持续轨迹 / 姿态目标
```

Continuous 的：

```text
stream_id
deadman
stop / zero
TTL
cancel
```

完整执行规则在后续“控制边界”阶段实现。

基础合同只冻结两类语义必须可区分。

---

# 14. VehicleCommand

VehicleCommand 与 Effect 是两个不同合同。

正式链路：

```text
Action
  ↓
Typed Effect
  ↓
Execution
  ↓
Authorization
  ↓
Safety
  ↓
VehicleCommand
  ↓
VehicleCommandPort
```

目标架构要求车辆相关 Effect 必须经过系统 SEND、Action SEND、Authorization 与 Safety 后才可交给 VehicleCommandPort。

---

## 14.1 Effect 的含义

```text
希望发生什么
```

## 14.2 VehicleCommand 的含义

```text
控制边界已经批准准备提交什么
```

因此 VehicleCommandEnvelope 才允许携带：

```text
run_id
lease identity
authorization generation
send generation
expected link session
deadline
priority
idempotency identity
```

旧项目现有 `VehicleCommandEnvelope` 可以作为新合同的重要迁移参考，但最终字段必须遵循本规范的时间与 Identity 类型。

---

# 15. Ports

Ports 只定义跨层能力边界，不暴露具体实现。

---

## 15.1 VehicleStatePort

职责：

```text
读取标准 VehicleState
```

不提供车辆控制。

---

## 15.2 LocalizationPort

职责：

```text
读取当前 LocalizationEstimate
```

具体实现可以是：

```text
flight controller
VIO
LiDAR SLAM
fusion
fake
replay
```

消费者不依赖实现类型。

---

## 15.3 WorldQueryPort

高级自主模块主要状态入口：

```text
snapshot() -> WorldSnapshot
```

Mission、Action、Planning、Guidance 默认不得直接绕过 World Model 分别读取：

```text
MAVLink
YOLO
LiDAR
GPS
Camera
```

---

## 15.4 VehicleCommandPort

V1 冻结为窄写接口：

```text
submit(command)
cancel(request)
status(command_id)
```

不允许重新出现：

```text
port.takeoff()
port.goto()
port.local_position()
port.set_servo()
port.send_body_velocity()
```

这类功能方法。

否则上层容易直接绕过 Execution。

---

# 16. 基础合同明确不包含的内容

以下内容不进入当前 V1 基础合同冻结范围。

### 原比赛 FIELD

不迁移。

### 投放 / 水瓶 Payload

不进入通用 Core。

### payload_release

属于具体 Application / Vehicle capability。

### Servo 特殊投放逻辑

暂不进入通用 Effect 基础集。

### YOLO Lock Target

属于后续 Perception control / Application 能力。

### MAVLink Frame ID

只存在 Protocol / Vehicle Adapter。

### ArduPilot 参数

不进入 Core。

### Mission 任务参数

不进入基础合同。

### Competition Environment

属于具体 Environment / Application。

---

# 17. 基础合同依赖规则

以下图示冻结数据与职责的流向；代码依赖仍须通过合同和端口保持向内：

```text
Core primitives
     ↓
Observation / VehicleState
     ↓
Perception / Localization / Mapping
     ↓
World Model
     ↓
WorldSnapshot
     ↓
Mission / Action / Planning / Guidance
     ↓
Typed Effect
     ↓
Execution
     ↓
Authorization / Safety
     ↓
VehicleCommand
     ↓
VehicleCommandPort
     ↓
Vehicle Plugin
     ↓
Protocol
     ↓
Transport
```

目标架构同样规定 Core、Mission、Action、Planning、Guidance、Perception 和 World Model 不得获得协议连接、Transport 或第二条车辆命令出口。

---

# 18. 推荐目标目录

V1 基础合同建议最终组织为：

```text
contracts/
│
├── core/
│   ├── identity.py
│   ├── version.py
│   ├── time.py
│   ├── frames.py
│   ├── geometry.py
│   ├── transform.py
│   └── quality.py
│
├── sensor/
│   └── observation.py
│
├── vehicle/
│   ├── state.py
│   ├── command.py
│   └── ports.py
│
├── localization/
│   ├── estimate.py
│   └── ports.py
│
├── world/
│   ├── snapshot.py
│   └── ports.py
│
└── effects/
    ├── common.py
    └── vehicle.py
```

只创建当前确实需要的包。

不得为了满足目录图而创建大量无实现空模块。

---

# 19. 原项目迁移原则

原 `cuadc2026` 不直接整体复制 contracts。

按下面方式处理：

### 可作为基础继续使用

```text
SchemaVersion
ResourceVersion
FrozenJson
ID 类型
Core monotonic clock 思路
VehicleCommandEnvelope 的执行 fencing 思路
submit / cancel / status 型 VehicleCommandPort
```

### 需要重构后迁移

```text
VehicleStateSnapshot
Typed Effects
时间类型
Perception DTO
```

### 不进入新基础合同

```text
contracts/state.py 旧 RuntimeSnapshot
Mapping[str, Any] Effect
功能方法式 VehicleCommandPort
MAVLink frame constants
FIELD 特殊坐标
control_allowed
age_s
SourceId(real/sitl/test)
```

旧代码需要时通过 Compatibility Adapter 使用。

---

# 20. 基础合同验收标准

完成基础合同实现后，至少需要测试：

### Geometry

- 拒绝 NaN / Infinity；
- Quaternion 合法性；
- 单位约定固定。

### Frame

- 空 FrameId 拒绝；
- 空间数据必须有 Frame。

### Transform

- ENU/NED 转换正确；
- FLU/FRD 转换正确；
- Static Transform 正确；
- Dynamic Transform 按时间查询；
- 缺失 Transform 明确失败。

### Time

- monotonic 不允许负数；
- UTC 必须带 timezone；
- 不同 clock domain 禁止直接 elapsed 比较。

### Observation

- typed data；
- identity 有效；
- timestamp 有效；
- spatial observation 必须有 Frame。

### VehicleState

- 不包含 Authorization / SEND；
- 不包含 MAVLink 常量；
- reported pose 使用统一坐标合同。

### Localization

- 与 VehicleState 语义独立；
- FlightController / Fake Localization 可以互换。

### WorldSnapshot

- immutable；
- versioned；
- dependencies 可追踪；
- freshness 固定于 Snapshot；
- consumer 不读取设备后门。

### Effect

- 参数强类型；
- 不含协议细节；
- 不含 Authorization generation；
- spatial effect 必须声明 Frame。

### VehicleCommandPort

只能通过：

```text
submit
cancel
status
```

写入。

---

# 21. 冻结结论

截至 V1.0，以下核心语义视为冻结：

```text
ROS-style ENU / FLU / Optical
FrameId +统一 Transform
TimePoint
captured / received / published time separation
Typed Geometry
Quality + Freshness separation
Typed Observation
VehicleState = 车辆自身报告状态
LocalizationEstimate = 定位模块输出
WorldSnapshot.localization = 系统最终采用定位
Immutable WorldSnapshot
Typed Effect
Effect ≠ VehicleCommand
submit/cancel/status VehicleCommandPort
```

原项目 FIELD、比赛投放和具体 MAVLink 语义不进入基础合同。

下一阶段应停止继续扩展基础抽象，直接使用 Fake / File 输入验证：

```text
Sensor Adapter
      ↓
Perception / Localization
      ↓
World Model
      ↓
WorldSnapshot
```

只有该状态链遇到无法由现有基础合同正确表达的真实问题时，才允许提出 V1 基础合同变更。

这也对应目标架构对状态链验收的要求：统一合同必须保证时间戳、坐标系、来源和质量能够被核对。
